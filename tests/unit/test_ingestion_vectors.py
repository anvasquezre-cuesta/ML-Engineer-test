"""Classify Qdrant errors without retrying writes or exposing response bodies."""

import asyncio

import httpx
import pytest
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.core.config import Settings
from app.services.ingestion_vectors import (
    IngestionVectorStore, VectorRequestError, VectorTimeoutError, VectorUnavailableError,
)


def store():
    result = object.__new__(IngestionVectorStore)
    result.settings = Settings(qdrant_read_retries=2)
    return result


def response(status):
    return UnexpectedResponse(status, "private reason", b"private document or credentials", httpx.Headers())


@pytest.mark.parametrize("error", [
    response(429), response(500), response(502), response(503), response(504),
    ResponseHandlingException(httpx.ConnectError("private")),
    ResponseHandlingException(httpx.ReadTimeout("private")),
    ResponseHandlingException(TimeoutError("private")),
    httpx.ConnectError("private"), httpx.ReadTimeout("private"), TimeoutError("private"),
])
def test_transient_read_retries_then_succeeds_without_leaking(monkeypatch, error):
    async def no_delay(_):
        pass
    monkeypatch.setattr("app.services.ingestion_vectors.asyncio.sleep", no_delay)

    async def run():
        calls = []
        async def read():
            calls.append(1)
            if len(calls) < 3:
                raise error
            return "ok"
        assert await store()._call(read, read=True) == "ok"
        assert len(calls) == 3
    asyncio.run(run())


@pytest.mark.parametrize("error,kind", [
    (ResponseHandlingException(httpx.ReadTimeout("private")), VectorTimeoutError),
    (TimeoutError("private"), VectorTimeoutError),
    (httpx.ConnectError("private"), VectorUnavailableError),
    (response(503), VectorUnavailableError),
    (response(400), VectorRequestError),
    (response(401), VectorRequestError),
    (response(None), VectorRequestError),
    (ResponseHandlingException(ValueError("private")), VectorRequestError),
])
def test_failure_type_and_no_automatic_write_retry(error, kind):
    async def run():
        calls = []
        async def write():
            calls.append(1)
            raise error
        with pytest.raises(kind) as failure:
            await store()._call(write)
        assert calls == [1]
        assert "private" not in str(failure.value)
    asyncio.run(run())


@pytest.mark.parametrize("error", [response(400), response(401), response(None),
                                   ResponseHandlingException(ValueError("private"))])
def test_nontransient_reads_are_not_retried(error):
    async def run():
        calls = []
        async def read():
            calls.append(1)
            raise error
        with pytest.raises(VectorRequestError):
            await store()._call(read, read=True)
        assert calls == [1]
    asyncio.run(run())


def test_programming_error_is_not_retried_or_disguised_as_outage():
    async def run():
        calls = []
        async def read():
            calls.append(1)
            raise ValueError("bug")
        with pytest.raises(ValueError):
            await store()._call(read, read=True)
        assert calls == [1]
    asyncio.run(run())


def test_cancellation_during_backoff_does_not_start_another_request(monkeypatch):
    async def run():
        started = asyncio.Event()
        calls = []
        async def wait(_):
            started.set()
            await asyncio.Event().wait()
        monkeypatch.setattr("app.services.ingestion_vectors.asyncio.sleep", wait)
        async def read():
            calls.append(1)
            raise httpx.ConnectError("private")
        task = asyncio.create_task(store()._call(read, read=True))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert calls == [1]
    asyncio.run(run())
