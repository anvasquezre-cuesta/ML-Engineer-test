import asyncio
from io import BytesIO
from threading import Event

import pytest
from starlette.datastructures import UploadFile

from app.core.config import Settings
from app.models.document import OCRDocument, OCRPage
from app.services.chunking_service import TextChunk
from app.services.embedding_async import PreparedDocument
from app.services.ingestion_ledger import IngestionLedger, LedgerStateError, PageRecord
from app.services.ingestion_service import IngestionService, IngestionTimeoutError, NoDocumentTextError
from app.services.ingestion_vectors import VectorStoreError
from app.services.ocr_service import _run_blocking


class OCR:
    def __init__(self, empty=False): self.empty = empty
    async def extract_async(self, data):
        return OCRDocument((OCRPage(0, 500, 300, "", ()), OCRPage(1, 500, 300, "" if self.empty else "Alice Smith", ())))


class Embeddings:
    async def prepare(self, pages):
        return PreparedDocument(
            [TextChunk(1, 0, "Alice Smith", 0, 11, 4)],
            [PageRecord(0, False, 0), PageRecord(1, True, 1)], [[0.1] * 384],
        )
    async def aclose(self): pass


class Vectors:
    lock_name = "collection-test"
    ledger_id = "test-ledger"
    def __init__(self, fail=False): self.fail, self.points = fail, []
    async def ensure(self, **kwargs): pass
    async def upsert(self, points):
        self.points.extend(points)
        if self.fail: raise VectorStoreError("unknown outcome")
    async def verify(self, record): assert len(self.points) == record.expected_chunks
    async def aclose(self): pass


def run_service(tmp_path, *, empty=False, fail=False):
    settings = Settings(ingestion_ledger_path=str(tmp_path / "private" / "ledger.sqlite3"))
    ledger = IngestionLedger(settings.ingestion_ledger_path)
    vectors = Vectors(fail)
    service = IngestionService(OCR(empty), settings, ledger=ledger, embeddings=Embeddings(), vectors=vectors)
    return service, ledger, vectors


def test_success_preserves_physical_pages_and_marks_complete(tmp_path):
    service, ledger, vectors = run_service(tmp_path)
    async def run():
        upload = UploadFile(BytesIO(b"pdf"), filename="../source.pdf")
        try:
            response = await service.ingest(upload)
        finally:
            await upload.close()
            await service.aclose()
        assert response.model_dump() == {"status": "success", "chunks_stored": 1}
    asyncio.run(run())
    point = vectors.points[0]
    record = ledger.get(point.payload["ingestion_id"])
    assert record.state == "completed" and not record.write_uncertain
    assert point.payload["source_file"] == "source.pdf" and point.payload["page_number"] == 1
    assert ledger.pages(record.ingestion_id) == [PageRecord(0, False, 0), PageRecord(1, True, 1)]


def test_unknown_remote_write_is_persisted_as_cleanup_pending(tmp_path):
    service, ledger, vectors = run_service(tmp_path, fail=True)
    async def run():
        with pytest.raises(VectorStoreError):
            await service.ingest(UploadFile(BytesIO(b"pdf")))
        await service.aclose()
    asyncio.run(run())
    record = ledger.get(vectors.points[0].payload["ingestion_id"])
    assert record.state == "cleanup_pending" and record.write_uncertain


def test_all_empty_document_records_pages_but_never_writes_vectors(tmp_path):
    service, ledger, vectors = run_service(tmp_path, empty=True)
    async def run():
        with pytest.raises(NoDocumentTextError):
            await service.ingest(UploadFile(BytesIO(b"pdf")))
        await service.aclose()
    asyncio.run(run())
    import hashlib
    record = ledger.find_by_content(hashlib.sha256(b"pdf").hexdigest())[0]
    assert record.state == "failed" and not vectors.points
    assert ledger.pages(record.ingestion_id) == [PageRecord(0, False, 0), PageRecord(1, False, 0)]


def test_cancelled_remote_write_keeps_uncertainty_and_releases_ownership_only_after_recording(tmp_path):
    service, ledger, vectors = run_service(tmp_path)
    async def run():
        started = asyncio.Event()
        async def slow(points):
            vectors.points.extend(points)
            started.set()
            await asyncio.Event().wait()
        vectors.upsert = slow
        task = asyncio.create_task(service.ingest(UploadFile(BytesIO(b"pdf"))))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        record = ledger.get(vectors.points[0].payload["ingestion_id"])
        assert record.state == "cleanup_pending" and record.write_uncertain
        with ledger.attempt_lock(record.ingestion_id):
            assert not service._tasks
        await service.aclose()
    asyncio.run(run())


def test_repeated_cancellation_waits_for_blocking_work():
    started, release = Event(), Event()

    def work():
        started.set()
        assert release.wait(5)

    async def run():
        task = asyncio.create_task(_run_blocking(work))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())


def test_repeated_cancel_and_shutdown_do_not_release_active_ledger_lock(tmp_path):
    service, ledger, vectors = run_service(tmp_path)
    fail_started, release = Event(), Event()
    original_fail = ledger.fail

    def slow_fail(*args):
        fail_started.set()
        assert release.wait(5)
        return original_fail(*args)

    ledger.fail = slow_fail

    async def run():
        write_started = asyncio.Event()

        async def slow_write(points):
            vectors.points.extend(points)
            write_started.set()
            await asyncio.Event().wait()

        vectors.upsert = slow_write
        task = asyncio.create_task(service.ingest(UploadFile(BytesIO(b"pdf"))))
        close_task = None
        try:
            await asyncio.wait_for(write_started.wait(), 2)
            task.cancel()
            assert await asyncio.to_thread(fail_started.wait, 2)
            task.cancel()
            close_task = asyncio.create_task(service.aclose())
            await asyncio.sleep(0.02)
            assert not task.done() and not close_task.done()
            ingestion_id = vectors.points[0].payload["ingestion_id"]
            with pytest.raises(LedgerStateError), ledger.attempt_lock(ingestion_id):
                pass
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await close_task
        record = ledger.get(ingestion_id)
        assert record.state == "cleanup_pending" and record.write_uncertain
        with ledger.attempt_lock(ingestion_id):
            pass

    asyncio.run(run())


def test_overall_deadline_during_write_leaves_uncertain_cleanup(tmp_path):
    service, ledger, vectors = run_service(tmp_path)
    service.settings = service.settings.model_copy(update={"ingest_job_timeout_seconds": 0.1})

    async def run():
        async def slow_write(points):
            vectors.points.extend(points)
            await asyncio.Event().wait()

        vectors.upsert = slow_write
        with pytest.raises(IngestionTimeoutError):
            await service.ingest(UploadFile(BytesIO(b"pdf")))
        await service.aclose()

    asyncio.run(run())
    record = ledger.get(vectors.points[0].payload["ingestion_id"])
    assert record.state == "cleanup_pending" and record.write_uncertain
