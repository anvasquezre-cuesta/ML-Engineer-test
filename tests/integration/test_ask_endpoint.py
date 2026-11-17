"""HTTP question contract; embedding, retrieval and generation are simulated."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_ask_service
from app.api.rag import router
from app.core.config import Settings
from app.core.request_limits import ExtractionBodyLimitMiddleware
from app.services.ask_service import AskService, CitationEvidence, GeneratedAnswer, RetrievedFragment
from app.services.answer_generator import (
    GeneratorConfigurationError, GeneratorInvalidResponseError, GeneratorRateLimitError,
    GeneratorTimeoutError, GeneratorUnavailableError,
)
from app.services.embedding_service import EmbeddingInputError, EmbeddingProcessingError
from app.services.ingestion_ledger import LedgerError
from app.services.ingestion_vectors import (
    VectorCompatibilityError, VectorRequestError, VectorStoreError, VectorTimeoutError, VectorUnavailableError,
)


class Embedder:
    async def embed_query(self, text):
        return [1.0]


class Retriever:
    def __init__(self, fragments):
        self.fragments = fragments

    async def retrieve(self, vector, *, limit):
        return self.fragments


class Generator:
    def __init__(self):
        self.calls = 0

    async def generate(self, question, context):
        self.calls += 1
        return GeneratedAnswer("A grounded answer", (CitationEvidence(context[0].citation_id, context[0].text),))


def app_for(monkeypatch, service, **kwargs):
    settings = Settings(**kwargs)
    monkeypatch.setattr("app.api.rag.get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.add_middleware(ExtractionBodyLimitMiddleware, path="/api/ask",
                       max_request_bytes=settings.ask_max_request_bytes,
                       max_in_flight=settings.ask_max_in_flight,
                       upload_timeout_seconds=settings.ask_upload_timeout_seconds)
    app.dependency_overrides[get_ask_service] = lambda: service
    return app


def test_disabled_by_default_and_openapi_contract(monkeypatch):
    app = app_for(monkeypatch, None)
    with TestClient(app) as client:
        assert client.post("/api/ask", json={"question": "Question?"}).status_code == 503
        operation = client.get("/openapi.json").json()["paths"]["/api/ask"]["post"]
        assert "application/json" in operation["requestBody"]["content"]


def test_real_application_has_no_generator_enabled_by_default():
    from app.main import app
    with TestClient(app) as client:
        response = client.post("/api/ask", json={"question": "Question?"})
        assert response.status_code == 503
        assert response.json() == {"detail": "Question answering is not configured"}
        assert app.state.ingestion_service.embeddings._process is None


def test_success_returns_only_cited_sources_and_no_cache(monkeypatch):
    generator = Generator()
    service = AskService(Embedder(), Retriever([RetrievedFragment("context", "doc page 1")]), generator)
    with TestClient(app_for(monkeypatch, service)) as client:
        result = client.post("/api/ask", json={"question": "  Question?  "})
        assert result.status_code == 200
        assert result.json() == {"answer": "A grounded answer", "sources": ["doc page 1"]}
        assert result.headers["cache-control"] == "no-store"
    assert generator.calls == 1


def test_no_evidence_does_not_call_generator(monkeypatch):
    generator = Generator()
    service = AskService(Embedder(), Retriever([]), generator)
    with TestClient(app_for(monkeypatch, service)) as client:
        response = client.post("/api/ask", json={"question": "Question?"})
        assert response.status_code == 200 and response.json()["sources"] == []
    assert generator.calls == 0


@pytest.mark.parametrize("body", [b'{"question":', b'{"question":"  "}', b'{"other":"private"}',
                                   b'{"question":7}', b'{"question":"' + b'x' * 2001 + b'"}'])
def test_invalid_requests_do_not_echo_sensitive_input(monkeypatch, body, caplog):
    with TestClient(app_for(monkeypatch, None)) as client:
        response = client.post("/api/ask", content=body, headers={"content-type": "application/json"})
        assert response.status_code == 422 and response.json() == {"detail": "Invalid question"}
    assert "private" not in response.text and "private" not in caplog.text


@pytest.mark.parametrize("error,status", [
    (EmbeddingInputError("private"), 422), (EmbeddingProcessingError("private"), 503),
    (LedgerError("private"), 503), (VectorStoreError("private"), 503), (RuntimeError("private"), 500),
    (GeneratorRateLimitError("private"), 429),
])
def test_dependency_failures_do_not_leak_exception_details(monkeypatch, error, status, caplog):
    class Broken:
        async def ask(self, question):
            raise error
    with TestClient(app_for(monkeypatch, Broken())) as client:
        response = client.post("/api/ask", json={"question": "sensitive question"})
        assert response.status_code == status and "private" not in response.text
    assert "sensitive question" not in caplog.text and "private" not in caplog.text


@pytest.mark.parametrize("error,status,detail", [
    (GeneratorTimeoutError("private"), 504, "Model provider timed out"),
    (GeneratorConfigurationError("private"), 503, "Model provider rejected its configuration or request"),
    (GeneratorUnavailableError("private"), 503, "Model provider is unavailable"),
    (GeneratorInvalidResponseError("private"), 503, "Model response or citation evidence is invalid"),
    (VectorTimeoutError("private"), 504, "Vector store timed out"),
    (VectorCompatibilityError("private"), 503, "Vector collection and ingestion ledger are incompatible"),
    (VectorUnavailableError("private"), 503, "Vector store is unavailable"),
    (VectorRequestError("private"), 503, "Vector store rejected the request or returned an invalid response"),
])
def test_specific_dependency_failure_does_not_poison_later_requests(monkeypatch, error, status, detail, caplog):
    from app.services.ask_service import Answer
    class FailsOnce:
        calls = 0
        async def ask(self, question):
            self.calls += 1
            if self.calls == 1:
                raise error
            return Answer("Recovered", ())
    with TestClient(app_for(monkeypatch, FailsOnce())) as client:
        failed = client.post("/api/ask", json={"question": "private question"})
        assert failed.status_code == status and failed.json() == {"detail": detail}
        recovered = client.post("/api/ask", json={"question": "next"})
        assert recovered.status_code == 200 and recovered.json()["answer"] == "Recovered"
    assert "private" not in failed.text and "private" not in caplog.text


def test_body_limit_and_processing_timeout(monkeypatch):
    class Slow:
        async def ask(self, question):
            await asyncio.sleep(1)
    app = app_for(monkeypatch, Slow(), ask_max_request_bytes=64, ask_job_timeout_seconds=0.02)
    with TestClient(app) as client:
        assert client.post("/api/ask", json={"question": "a" * 100}).status_code == 413
        assert client.post("/api/ask", json={"question": "a"}).status_code == 504


def test_capacity_is_bounded_and_cancellation_releases_it(monkeypatch):
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        class Slow:
            async def ask(self, question):
                started.set()
                await release.wait()
        app = app_for(monkeypatch, Slow(), ask_max_in_flight=1)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = asyncio.create_task(client.post("/api/ask", json={"question": "first"}))
            try:
                await asyncio.wait_for(started.wait(), 2)
                assert (await client.post("/api/ask", json={"question": "second"})).status_code == 503
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
            finally:
                release.set()
            # A new request reaches the service instead of being rejected for capacity.
            next_response = await client.post("/api/ask", json={"question": "next"})
            assert next_response.status_code != 503
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_http_connector_with_mocked_provider_protocol(monkeypatch, provider):
    from app.services.answer_generator import HTTPAnswerGenerator

    async def run():
        def handler(request):
            text = '{"answer":"Based on the record","citations":[{"id":"S1","quote":"facts"}]}'
            if provider == "openai":
                payload = {"choices": [{"message": {"content": text}}]}
            else:
                payload = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
            return httpx.Response(200, json=payload)
        provider_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
        settings = Settings(llm_provider=provider, llm_model="test-model", llm_api_key="test-key", llm_allow_external=True)
        generator = HTTPAnswerGenerator(settings, client=provider_client)
        app = app_for(monkeypatch, AskService(Embedder(), Retriever([RetrievedFragment("facts", "source")]), generator))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/ask", json={"question": "What happened?"})
                assert response.status_code == 200
                assert response.json() == {"answer": "Based on the record", "sources": ["source"]}
        finally:
            await generator.aclose()
    asyncio.run(run())


def test_fabricated_quote_is_rejected_without_retry_or_leak(monkeypatch, caplog):
    from app.services.answer_generator import HTTPAnswerGenerator

    async def run():
        calls = []
        def handler(request):
            calls.append(1)
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                "answer": "private invented answer",
                "citations": [{"id": "S1", "quote": "invented secret evidence"}],
            })}}]})
        import json
        provider_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
        generator = HTTPAnswerGenerator(Settings(llm_provider="openai", llm_model="test", llm_api_key="test-key",
                                                  llm_allow_external=True), client=provider_client)
        app = app_for(monkeypatch, AskService(Embedder(), Retriever([RetrievedFragment("actual facts", "source")]), generator))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/ask", json={"question": "private question"})
                assert response.status_code == 503
                assert "invented" not in response.text and "private" not in response.text
                assert calls == [1]
        finally:
            await generator.aclose()
    asyncio.run(run())
    assert "private question" not in caplog.text and "invented secret evidence" not in caplog.text
