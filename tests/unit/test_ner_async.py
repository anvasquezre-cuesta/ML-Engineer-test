import asyncio
from concurrent.futures import ThreadPoolExecutor

import anyio
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_ner_service
from app.core.config import Settings
from app.main import lifespan
from app.models.extraction import PersonSpan
from app.services.ner_async import NERService, _parse_result, _start_worker
from app.services.ner_service import NERBusyError, NERInputError, NERProcessingError, NERTimeoutError


def test_lifespan_shares_lazy_ner_service():
    app = FastAPI(lifespan=lifespan)

    @app.get("/test-ner")
    def service_id(service: NERService = Depends(get_ner_service)):
        return {"id": id(service), "started": any(slot.process for slot in service._slots)}

    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(lambda _: client.get("/test-ner").json(), range(8)))
        assert len({response["id"] for response in responses}) == 1
        assert all(not response["started"] for response in responses)


def test_limits_are_checked_before_dispatch(monkeypatch):
    async def unexpected(*args):
        raise AssertionError("invalid input was dispatched")

    monkeypatch.setattr(NERService, "_execute_job", unexpected)

    async def run():
        service = NERService(Settings(max_pdf_pages=2, ner_max_page_chars=3, ner_max_document_chars=4))
        try:
            for pages in (["abcd"], ["abc", "de"], ["a", "b", "c"], "abc", [None]):
                with pytest.raises(NERInputError):
                    await service.detect_pages(pages)
        finally:
            await service.aclose()

    asyncio.run(run())


def test_saturation_and_started_cancellation_keep_capacity_until_job_finishes(monkeypatch):
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()

        async def fake_job(self, pages):
            started.set()
            await finish.wait()
            return [[] for _ in pages]

        monkeypatch.setattr(NERService, "_execute_job", fake_job)
        service = NERService(Settings(ner_max_concurrent_jobs=1, ner_max_queued_jobs=0))
        first = asyncio.create_task(service.detect_pages(["first"]))
        try:
            await started.wait()
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            with pytest.raises(NERBusyError, match="capacity"):
                await service.detect_pages(["second"])
            assert len(service._tasks) == 1
            finish.set()
        finally:
            await service.aclose()
        assert not service._tasks

    asyncio.run(run())


def test_queued_cancellation_never_dispatches_the_job(monkeypatch):
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        received = []

        async def fake_job(self, pages):
            received.append(pages)
            started.set()
            await finish.wait()
            return [[] for _ in pages]

        monkeypatch.setattr(NERService, "_execute_job", fake_job)
        service = NERService(Settings(ner_max_concurrent_jobs=1, ner_max_queued_jobs=1))
        first = asyncio.create_task(service.detect_pages(["first"]))
        await started.wait()
        second = asyncio.create_task(service.detect_pages(["second"]))
        await asyncio.sleep(0.05)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        finish.set()
        await first
        await service.aclose()
        assert received == [("first",)]

    asyncio.run(run())


def test_queue_and_job_timeouts_release_capacity(monkeypatch):
    async def fake_job(self, pages):
        await asyncio.sleep(5)
        return [[] for _ in pages]

    monkeypatch.setattr(NERService, "_execute_job", fake_job)

    async def run():
        service = NERService(Settings(
            ner_max_concurrent_jobs=1, ner_max_queued_jobs=1,
            ner_queue_timeout_seconds=0.05, ner_job_timeout_seconds=0.2,
        ))
        try:
            first = asyncio.create_task(service.detect_pages(["first"]))
            await asyncio.sleep(0.02)
            with pytest.raises(NERBusyError, match="queue"):
                await service.detect_pages(["second"])
            with pytest.raises(NERTimeoutError):
                await first
        finally:
            await service.aclose()
        assert not service._tasks

    asyncio.run(run())


def test_anyio_cancellation_keeps_started_work_supervised(monkeypatch):
    async def run():
        started, finished = anyio.Event(), anyio.Event()

        async def fake_job(self, pages):
            started.set()
            await asyncio.sleep(0.1)
            finished.set()
            return [[] for _ in pages]

        monkeypatch.setattr(NERService, "_execute_job", fake_job)
        service = NERService()
        async with anyio.create_task_group() as group:
            group.start_soon(service.detect_pages, ["name"])
            await started.wait()
            group.cancel_scope.cancel()
        await service.aclose()
        assert finished.is_set()

    anyio.run(run)


def test_shutdown_rejects_new_jobs_and_is_idempotent():
    async def run():
        service = NERService()
        await asyncio.gather(service.aclose(), service.aclose())
        with pytest.raises(NERBusyError, match="shutting down"):
            await service.detect_pages(["test"])

    asyncio.run(run())


def test_cancellation_during_process_start_cleans_process(monkeypatch):
    async def run():
        creating, finish = asyncio.Event(), asyncio.Event()
        cleaned = []
        process = object()

        async def fake_start(*args, **kwargs):
            creating.set()
            await finish.wait()
            return process

        async def fake_terminate(worker):
            cleaned.append(worker)

        monkeypatch.setattr("app.services.ner_async.asyncio.create_subprocess_exec", fake_start)
        monkeypatch.setattr("app.services.ner_async._terminate_worker", fake_terminate)
        task = asyncio.create_task(_start_worker())
        await creating.wait()
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned == [process]

    asyncio.run(run())


@pytest.mark.parametrize("message", [
    {"status": "ok", "pages": []},
    {"status": "ok", "pages": [[{"text": "secret", "char_start": 0, "char_end": 6}]]},
    {"status": "ok", "pages": [[{"text": "Jane", "char_start": 0, "char_end": 100}]]},
    {"status": "ok", "pages": [[{"text": "Jane", "char_start": 0, "char_end": 4, "extra": 1}]]},
])
def test_invalid_worker_results_are_rejected_without_leaking_content(message):
    with pytest.raises(NERProcessingError) as caught:
        _parse_result(message, ("Jane",))
    assert "secret" not in str(caught.value)


def test_worker_result_round_trip_preserves_page_local_offsets():
    message = {"status": "ok", "pages": [[{"text": "Jane", "char_start": 3, "char_end": 7}], []]}
    assert _parse_result(message, ("Hi Jane", "")) == [[PersonSpan("Jane", 3, 7)], []]
