import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app.api.dependencies import get_ingestion_service
from app.api.rag import router
from app.core.config import Settings
from app.core.request_limits import ExtractionBodyLimitMiddleware
from app.models.schemas import IngestResponse


class Service:
    def __init__(self): self.calls = 0
    async def ingest(self, upload):
        self.calls += 1
        assert await upload.read() == b"pdf"
        return IngestResponse(status="success", chunks_stored=1)


def make_app(monkeypatch, **limits):
    settings = Settings(**limits)
    monkeypatch.setattr("app.api.rag.get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.add_middleware(
        ExtractionBodyLimitMiddleware, path="/api/ingest", max_request_bytes=settings.max_request_bytes,
        max_in_flight=1, upload_timeout_seconds=settings.ingest_upload_timeout_seconds,
    )
    service = Service()
    app.dependency_overrides[get_ingestion_service] = lambda: service
    return app, service


def test_valid_multipart_contract(monkeypatch):
    app, service = make_app(monkeypatch)
    with TestClient(app) as client:
        response = client.post("/api/ingest", files={"pdf_file": ("doc.pdf", b"pdf", "application/pdf")})
        schema = client.get("/openapi.json").json()["paths"]["/api/ingest"]["post"]["requestBody"]
    assert response.status_code == 200 and response.json() == {"status": "success", "chunks_stored": 1}
    assert service.calls == 1 and schema["content"]["multipart/form-data"]["schema"]["required"] == ["pdf_file"]


def test_extra_parts_and_file_limit_are_rejected_before_service(monkeypatch):
    app, service = make_app(monkeypatch, max_upload_bytes=2)
    with TestClient(app) as client:
        assert client.post("/api/ingest", files={"pdf_file": ("x", b"pdf")}).status_code == 413
        assert client.post("/api/ingest", data={"pdf_file": "not-file"}).status_code == 422
        assert client.post("/api/ingest", files={"pdf_file": ("x", b"a")}, data={"extra": "no"}).status_code == 422
    assert service.calls == 0


def test_chunked_and_slow_upload_are_bounded(monkeypatch):
    app, service = make_app(monkeypatch, max_request_bytes=10, ingest_upload_timeout_seconds=0.03)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            async def chunks():
                yield b"a" * 11
            excessive = await client.post("/api/ingest", content=chunks(), headers={"Content-Type": "multipart/form-data; boundary=x"})
            async def slow():
                await asyncio.sleep(0.1)
                yield b"x"
            timed_out = await client.post("/api/ingest", content=slow(), headers={"Content-Type": "multipart/form-data; boundary=x"})
            return excessive, timed_out
    excessive, timed_out = asyncio.run(run())
    assert excessive.status_code == 413 and timed_out.status_code == 408 and service.calls == 0


def test_capacity_is_rejected_without_consuming_second_request(monkeypatch):
    app, service = make_app(monkeypatch)
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        async def waiting(upload):
            started.set()
            await finish.wait()
            return IngestResponse(status="success", chunks_stored=1)
        service.ingest = waiting
        consumed = []
        async def body():
            consumed.append(True)
            yield b"not-read"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = asyncio.create_task(client.post("/api/ingest", files={"pdf_file": ("x", b"pdf")}))
            try:
                await asyncio.wait_for(started.wait(), 2)
                second = await client.post("/api/ingest", content=body())
                assert second.status_code == 503 and not consumed
            finally:
                finish.set()
                await first
    asyncio.run(run())


@pytest.mark.parametrize("exception,status", [
    ("InvalidPDFError", 400), ("PDFPageCountError", 413), ("OCRDocumentTimeoutError", 504),
    ("OCRUploadTimeoutError", 408), ("EmbeddingTimeoutError", 504), ("IngestionTimeoutError", 504), ("ChunkingError", 422),
    ("ChunkingLimitError", 413), ("NoDocumentTextError", 422), ("VectorStoreError", 503), ("LedgerError", 503),
])
def test_domain_errors_are_mapped_without_document_text(monkeypatch, exception, status):
    import app.api.rag as module
    app, service = make_app(monkeypatch)
    async def fail(upload):
        raise getattr(module, exception)("private document text")
    service.ingest = fail
    with TestClient(app) as client:
        result = client.post("/api/ingest", files={"pdf_file": ("x", b"pdf")})
    assert result.status_code == status and "private document text" not in result.text


@pytest.mark.parametrize("exception,status,detail", [
    ("VectorTimeoutError", 504, "Vector store timed out; ingestion outcome may need inspection"),
    ("VectorCompatibilityError", 503, "Vector collection and ingestion ledger are incompatible"),
    ("VectorUnavailableError", 503, "Vector store is unavailable; ingestion outcome may need inspection"),
    ("VectorRequestError", 503, "Vector store rejected the request or returned an invalid response"),
])
def test_specific_vector_error_and_next_request(monkeypatch, exception, status, detail):
    import app.api.rag as module
    app, service = make_app(monkeypatch)
    original = service.ingest
    calls = []
    async def fails_once(upload):
        calls.append(1)
        if len(calls) == 1:
            raise getattr(module, exception)("private document text")
        return await original(upload)
    service.ingest = fails_once
    with TestClient(app) as client:
        failed = client.post("/api/ingest", files={"pdf_file": ("x", b"pdf")})
        assert failed.status_code == status and failed.json() == {"detail": detail}
        assert client.post("/api/ingest", files={"pdf_file": ("x", b"pdf")}).status_code == 200
    assert "private" not in failed.text
