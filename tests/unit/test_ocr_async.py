import asyncio
from io import BytesIO

import anyio
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models.document import OCRDocument
from app.services.ocr_service import (
    InvalidPDFError,
    OCRBusyError,
    OCRDocumentTimeoutError,
    OCRService,
    OCRUploadTimeoutError,
    PDFPageCountError,
    PDFTooLargeError,
    _start_worker,
)


def test_concurrency_limit_must_be_positive():
    with pytest.raises(ValidationError):
        Settings(ocr_max_concurrent_jobs=0)


def test_ocr_worker_does_not_block_event_loop(monkeypatch):
    async def fake_job(self, source, *, is_bytes):
        await asyncio.sleep(0.3)
        return OCRDocument(())

    monkeypatch.setattr(OCRService, "_execute_job", fake_job)

    async def run():
        service = OCRService(Settings(ocr_max_concurrent_jobs=1))
        task = asyncio.create_task(service.extract_async(b"test"))
        await asyncio.sleep(0.05)
        assert not task.done()
        assert await task == OCRDocument(())
        await service.aclose()

    asyncio.run(run())


def test_ocr_concurrency_and_queue_are_bounded(monkeypatch):
    active = 0
    peak = 0

    async def fake_job(self, source, *, is_bytes):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.15)
            return OCRDocument(())
        finally:
            active -= 1

    monkeypatch.setattr(OCRService, "_execute_job", fake_job)

    async def run():
        service = OCRService(Settings(ocr_max_concurrent_jobs=2, ocr_max_queued_jobs=2))
        tasks = [asyncio.create_task(service.extract_async(b"test")) for _ in range(4)]
        await asyncio.sleep(0.05)
        with pytest.raises(OCRBusyError, match="capacity"):
            await service.extract_async(b"another")
        assert len(await asyncio.gather(*tasks)) == 4
        await service.aclose()

    asyncio.run(run())
    assert peak == 2


def test_async_worker_propagates_pdf_validation_errors():
    async def run():
        service = OCRService()
        try:
            with pytest.raises(InvalidPDFError):
                await service.extract_async(b"not a PDF")
        finally:
            await service.aclose()

    asyncio.run(run())


def test_async_worker_preserves_page_count_limit_error():
    import pymupdf

    with pymupdf.open() as document:
        document.new_page()
        document.new_page()
        data = document.tobytes()

    async def run():
        service = OCRService(Settings(max_pdf_pages=1))
        try:
            with pytest.raises(PDFPageCountError):
                await service.extract_async(data)
        finally:
            await service.aclose()

    asyncio.run(run())


def test_oversized_async_input_is_rejected_before_dispatch(monkeypatch):
    async def unexpected_job(*args, **kwargs):
        raise AssertionError("oversized input was dispatched")

    monkeypatch.setattr(OCRService, "_execute_job", unexpected_job)

    async def run():
        service = OCRService(Settings(max_upload_bytes=4))
        with pytest.raises(PDFTooLargeError):
            await service.extract_async(b"12345")
        await service.aclose()

    asyncio.run(run())


def test_started_job_is_supervised_after_direct_cancellation(monkeypatch):
    async def run():
        started, finish, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def fake_job(self, source, *, is_bytes):
            started.set()
            await finish.wait()
            finished.set()
            return OCRDocument(())

        monkeypatch.setattr(OCRService, "_execute_job", fake_job)
        service = OCRService(Settings(ocr_max_concurrent_jobs=1, ocr_max_queued_jobs=0))
        task = asyncio.create_task(service.extract_async(b"test"))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(OCRBusyError):
            await service.extract_async(b"other")
        finish.set()
        await finished.wait()
        await service.aclose()
        assert not service._tasks

    asyncio.run(run())


def test_anyio_cancellation_keeps_started_job_supervised(monkeypatch):
    async def run():
        started = anyio.Event()
        finished = anyio.Event()

        async def fake_job(self, source, *, is_bytes):
            started.set()
            await asyncio.sleep(0.1)
            finished.set()
            return OCRDocument(())

        monkeypatch.setattr(OCRService, "_execute_job", fake_job)
        service = OCRService(Settings(ocr_max_concurrent_jobs=1))
        async with anyio.create_task_group() as group:
            group.start_soon(service.extract_async, b"test")
            await started.wait()
            group.cancel_scope.cancel()
        await service.aclose()
        assert finished.is_set()

    anyio.run(run)


def test_cancelled_queued_job_does_not_start(monkeypatch):
    async def run():
        started = asyncio.Event()
        finish = asyncio.Event()
        inputs = []

        async def fake_job(self, source, *, is_bytes):
            inputs.append(source)
            started.set()
            await finish.wait()
            return OCRDocument(())

        monkeypatch.setattr(OCRService, "_execute_job", fake_job)
        service = OCRService(Settings(ocr_max_concurrent_jobs=1, ocr_max_queued_jobs=1))
        first = asyncio.create_task(service.extract_async(b"first"))
        await started.wait()
        second = asyncio.create_task(service.extract_async(b"second"))
        await asyncio.sleep(0.05)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        finish.set()
        await first
        await service.aclose()
        assert inputs == [b"first"]

    asyncio.run(run())


def test_queue_and_document_deadlines(monkeypatch):
    async def fake_job(self, source, *, is_bytes):
        await asyncio.sleep(2)
        return OCRDocument(())

    monkeypatch.setattr(OCRService, "_execute_job", fake_job)

    async def run():
        service = OCRService(Settings(
            ocr_max_concurrent_jobs=1, ocr_max_queued_jobs=1,
            ocr_queue_timeout_seconds=0.1, ocr_document_timeout_seconds=0.3,
        ))
        first = asyncio.create_task(service.extract_async(b"first"))
        await asyncio.sleep(0.05)
        with pytest.raises(OCRBusyError, match="queue"):
            await service.extract_async(b"second")
        with pytest.raises(OCRDocumentTimeoutError):
            await first
        await service.aclose()

    asyncio.run(run())


def test_stream_admission_happens_before_reading_and_limits_bytes(monkeypatch):
    class Stream:
        def __init__(self, data):
            self.data = BytesIO(data)
            self.reads = 0

        async def read(self, size=-1):
            self.reads += 1
            return self.data.read(size)

    async def run():
        started, finish = asyncio.Event(), asyncio.Event()

        async def fake_job(self, source, *, is_bytes):
            started.set()
            await finish.wait()
            return OCRDocument(())

        monkeypatch.setattr(OCRService, "_execute_job", fake_job)
        service = OCRService(Settings(max_upload_bytes=4, ocr_max_concurrent_jobs=1, ocr_max_queued_jobs=0))
        first = asyncio.create_task(service.extract_async(b"test"))
        await started.wait()
        stream = Stream(b"12345")
        with pytest.raises(OCRBusyError):
            await service.extract_stream_async(stream)
        assert stream.reads == 0
        finish.set()
        await first
        with pytest.raises(PDFTooLargeError):
            await service.extract_stream_async(stream)
        await service.aclose()

    asyncio.run(run())


def test_slow_upload_times_out_and_releases_capacity(monkeypatch):
    class SlowStream:
        async def read(self, size=-1):
            await asyncio.sleep(5)
            return b""

    async def fake_job(self, source, *, is_bytes):
        return OCRDocument(())

    monkeypatch.setattr(OCRService, "_execute_job", fake_job)

    async def run():
        service = OCRService(Settings(
            ocr_max_concurrent_jobs=1, ocr_max_queued_jobs=0,
            ocr_upload_timeout_seconds=0.05,
        ))
        with pytest.raises(OCRUploadTimeoutError):
            await service.extract_stream_async(SlowStream())
        assert await service.extract_async(b"next") == OCRDocument(())
        await service.aclose()

    asyncio.run(run())


def test_shutdown_cancels_worker_after_deadline(monkeypatch):
    async def run():
        started, cleaned = asyncio.Event(), asyncio.Event()

        async def fake_job(self, source, *, is_bytes):
            started.set()
            try:
                await asyncio.sleep(5)
            finally:
                cleaned.set()

        monkeypatch.setattr(OCRService, "_execute_job", fake_job)
        service = OCRService(Settings(ocr_shutdown_timeout_seconds=0.05))
        request = asyncio.create_task(service.extract_async(b"test"))
        await started.wait()
        await service.aclose()
        assert cleaned.is_set()
        assert (await asyncio.gather(request, return_exceptions=True))[0].__class__ is asyncio.CancelledError
        with pytest.raises(OCRBusyError, match="shutting down"):
            await service.extract_async(b"test")

    asyncio.run(run())


def test_shutdown_during_upload_prevents_new_worker(monkeypatch):
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()

        class Stream:
            async def read(self, size=-1):
                if not started.is_set():
                    started.set()
                    await finish.wait()
                    return b"test"
                return b""

        service = OCRService()
        request = asyncio.create_task(service.extract_stream_async(Stream()))
        await started.wait()
        await service.aclose()
        finish.set()
        with pytest.raises(OCRBusyError, match="shutting down"):
            await request

    asyncio.run(run())


def test_cancel_during_worker_startup_cleans_process(monkeypatch):
    async def run():
        creating, finish = asyncio.Event(), asyncio.Event()
        cleaned = []
        process = object()

        async def fake_start(*args, **kwargs):
            creating.set()
            await finish.wait()
            return process

        async def fake_cleanup(proc):
            cleaned.append(proc)

        monkeypatch.setattr("app.services.ocr_service.asyncio.create_subprocess_exec", fake_start)
        monkeypatch.setattr("app.services.ocr_service._terminate_process_group", fake_cleanup)
        task = asyncio.create_task(_start_worker("fake"))
        await creating.wait()
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned == [process]

    asyncio.run(run())
