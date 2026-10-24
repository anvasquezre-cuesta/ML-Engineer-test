"""Resilience: timeouts, retries, failure modes (story 2.4).

Tests that LLM and vector-store calls carry timeout + retry from Settings,
every external-call failure surfaces as a meaningful domain error mapped to
HTTP 502, no silent except:pass, and structured logging carries doc ID
context through both pipelines.

All tests use fakes/stubs, no network, backoff=0 for fast red-phase.
"""

import re
import time
import logging
import pytest
from unittest import mock
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_embedding, get_vector_store, get_llm
from app.core.config import get_settings, Settings
from app.services.embedding_service import EmbeddingProvider
from app.services.vector_service import VectorStore
from app.services.rag_service import LLMClient, ingest_document, generate_answer


# --- Fake implementations ---

class CountingFakeEmbeddingProvider(EmbeddingProvider):
    """Embedding provider that counts calls and can optionally fail."""
    def __init__(self, fail_count=0):
        self.call_count = 0
        self.fail_count = fail_count

    def embed_documents(self, texts):
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise RuntimeError("embed_documents failed")
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text):
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise RuntimeError("embed_query failed")
        return [0.1, 0.2, 0.3]


class CountingFakeVectorStore(VectorStore):
    """In-memory vector store that counts calls and can optionally fail."""
    def __init__(self, fail_add=0, fail_query=0):
        """
        fail_add: number of add_chunks calls to fail before succeeding (0 = never)
        fail_query: number of query calls to fail before succeeding (0 = never)
        """
        self._data = {}
        self.fail_add = fail_add
        self.fail_query = fail_query
        self.add_call_count = 0
        self.query_call_count = 0

    def add_chunks(self, ids, embeddings, documents, metadatas):
        self.add_call_count += 1
        if self.add_call_count <= self.fail_add:
            raise RuntimeError(f"add_chunks failed on attempt {self.add_call_count}")
        for i, id_ in enumerate(ids):
            self._data[id_] = {
                "id": id_,
                "embedding": embeddings[i],
                "text": documents[i],
                "metadata": metadatas[i] if i < len(metadatas) else {}
            }

    @property
    def ids(self):
        return list(self._data.keys())

    @property
    def documents(self):
        return [v["text"] for v in self._data.values()]

    def query(self, query_embedding, top_k):
        self.query_call_count += 1
        if self.query_call_count <= self.fail_query:
            raise RuntimeError(f"query failed on attempt {self.query_call_count}")
        results = []
        for i, (id_, entry) in enumerate(self._data.items()):
            if i >= top_k:
                break
            results.append({
                "id": id_,
                "text": entry["text"],
                "metadata": entry["metadata"],
                "distance": 0.1 * i
            })
        return results


class CountingFakeLLMClient(LLMClient):
    """LLM client that counts calls and can optionally fail."""
    def __init__(self, response="The document mentions Margaret Thompson.", fail_count=0):
        """
        fail_count: number of calls to fail before succeeding.
                    0 = never fail. Use a high number like 999 for "always fails".
        """
        self.response = response
        self.fail_count = fail_count
        self.call_count = 0

    def complete(self, prompt):
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise RuntimeError(f"LLM complete failed on attempt {self.call_count}")
        return self.response


# Fixtures
@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_app_state():
    """Ensure clean dependency overrides for each test."""
    yield
    app.dependency_overrides.clear()


# AC-1: LLM timeout/exhausted retries -> 502
def test_ask_llm_timeout_returns_502_after_retries():
    """Given a stubbed LLM that raises on every attempt, when POST /api/ask is
    called, then 502 {detail} returns after the configured retry attempts."""
    store = CountingFakeVectorStore()
    embedder = CountingFakeEmbeddingProvider()
    llm = CountingFakeLLMClient(fail_count=999)

    app.dependency_overrides[get_embedding] = lambda: embedder
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm

    client = TestClient(app)

    # Ingest first (needs successful LLM, so temporarily swap in a good one)
    good_llm = CountingFakeLLMClient(response="ok")
    app.dependency_overrides[get_llm] = lambda: good_llm

    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()
    r = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text

    # Now swap in failing LLM for ask
    app.dependency_overrides[get_llm] = lambda: llm

    r = client.post("/api/ask", json={"question": "Who attended the meeting?"})
    # Should be 502 after retries (not 500, not hang)
    assert r.status_code == 502, f"Expected 502, got {r.status_code}: {r.text}"
    assert "detail" in r.json()


# AC-2: vector store errors on add_chunks -> 502
def test_ingest_vector_store_add_chunks_error_returns_502():
    """Given a stubbed vector store whose add_chunks raises on every attempt,
    when POST /api/ingest is called, then 502 {detail} after the configured retries."""
    store = CountingFakeVectorStore(fail_add=999)  # always fails
    embedder = CountingFakeEmbeddingProvider()
    llm = CountingFakeLLMClient(response="ok")

    app.dependency_overrides[get_embedding] = lambda: embedder
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm

    client = TestClient(app)

    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()
    r = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    # Should be 502 after retries
    assert r.status_code == 502, f"Expected 502, got {r.status_code}: {r.text}"
    assert "detail" in r.json()


# AC-3: vector store errors on query -> 502
def test_ask_vector_store_query_error_returns_502():
    """Given a stubbed vector store whose query raises on every attempt,
    when POST /api/ask is called, then 502 {detail} after the configured retries."""
    store = CountingFakeVectorStore(fail_query=999)
    embedder = CountingFakeEmbeddingProvider()
    llm = CountingFakeLLMClient(response="ok")

    app.dependency_overrides[get_embedding] = lambda: embedder
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm

    client = TestClient(app)

    # Ingest first (store add works, query fails)
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()
    r = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text

    # Now ask should fail on query
    r = client.post("/api/ask", json={"question": "Who attended the meeting?"})
    assert r.status_code == 502, f"Expected 502, got {r.status_code}: {r.text}"
    assert "detail" in r.json()


# AC-4: transient failure then success
def test_vector_store_transient_failure_then_success():
    """Given a stubbed vector store that fails once then succeeds, when ingest/ask
    is called, then 200 with the correct result and the observed call count equals
    retries+1 (retry genuinely retried, no sleep hang in tests)."""
    # Fail once, succeed on second try
    store = CountingFakeVectorStore(fail_add=1)  # transient failure
    embedder = CountingFakeEmbeddingProvider()
    llm = CountingFakeLLMClient(response="ok")

    app.dependency_overrides[get_embedding] = lambda: embedder
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm

    client = TestClient(app)

    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()
    r = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    # Verify retry happened: call count should be 2 (1 fail + 1 success)
    assert store.add_call_count == 2, f"Expected 2 add calls, got {store.add_call_count}"


# AC-5: retry count from Settings
def test_retry_count_comes_from_settings():
    """Given Settings configured with N retries and 0-second backoff, when an
    external call fails repeatedly, then exactly N+1 attempts occur (retry count
    comes from Settings, nothing hardcoded)."""
    # Override settings with N=1 retry, 0 backoff
    settings = get_settings()
    original_retries = settings.llm_max_retries
    original_backoff = settings.llm_backoff_seconds
    settings.llm_max_retries = 1
    settings.llm_backoff_seconds = 0.0

    # Store that always fails
    store = CountingFakeVectorStore(fail_add=999)
    embedder = CountingFakeEmbeddingProvider()
    llm = CountingFakeLLMClient(response="ok")

    app.dependency_overrides[get_embedding] = lambda: embedder
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm

    client = TestClient(app)

    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()
    r = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    assert r.status_code == 502, f"Expected 502, got {r.status_code}: {r.text}"
    # N+1 attempts = 2 (1 original + 1 retry)
    assert store.add_call_count == 2, f"Expected 2 add calls (1 retry), got {store.add_call_count}"

    # Restore settings
    settings.llm_max_retries = original_retries
    settings.llm_backoff_seconds = original_backoff


# AC-6: doc_id in ingest logs
def test_ingest_logs_doc_id(caplog):
    """Given a successful sample-PDF ingest, when log records are inspected, then
    a structured record carries the computed doc_id."""
    store = CountingFakeVectorStore()
    embedder = CountingFakeEmbeddingProvider()
    llm = CountingFakeLLMClient(response="ok")

    app.dependency_overrides[get_embedding] = lambda: embedder
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm

    # Capture logs
    caplog.set_level(logging.INFO, logger="app.services.rag_service")

    client = TestClient(app)

    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()
    r = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text

    # Check that doc_id appears in log
    found = False
    for record in caplog.records:
        if "doc_id" in record.getMessage().lower() or re.search(r"doc[_-]?id", record.getMessage()):
            found = True
            break
    assert found, f"No doc_id found in log records. Records: {[r.getMessage() for r in caplog.records]}"


# AC-7: ask logs retrieval context
def test_ask_logs_retrieval_context(caplog):
    """Given a successful ask against retrieved chunks, when log records are
    inspected, then a record carries the question and/or retrieved chunk ids."""
    store = CountingFakeVectorStore()
    embedder = CountingFakeEmbeddingProvider()
    llm = CountingFakeLLMClient(response="The document mentions Margaret Thompson.")

    app.dependency_overrides[get_embedding] = lambda: embedder
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm

    caplog.set_level(logging.INFO, logger="app.services.rag_service")

    client = TestClient(app)

    # Ingest first
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()
    r = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text

    # Now ask
    question = "Who attended the meeting?"
    r = client.post("/api/ask", json={"question": question})
    assert r.status_code == 200, r.text

    # Check that question or chunk ids appear in log
    found = False
    for record in caplog.records:
        msg = record.getMessage().lower()
        if "attended the meeting" in msg or "retrieved" in msg or "chunk" in msg:
            found = True
            break
    assert found, f"No retrieval context found in log records. Records: {[r.getMessage() for r in caplog.records]}"


# AC-8: silent-failure audit (no except:pass)
def test_no_silent_failure_in_rag_code():
    """Given the full app/ RAG path, when audited for except:pass/swallowing
    handlers, then none exist."""
    import subprocess
    # Grep for bare except: pass in app/
    result = subprocess.run(
        ["grep", "-rn", "except\\s*:\\s*pass", "app/"],
        capture_output=True, text=True,
        cwd="/home/varv0id/projects/ML-Engineer-test"
    )
    # Should find nothing
    assert result.returncode == 1 or result.stdout == "", f"Found bare except:pass in: {result.stdout}"

    # Also check for except Exception: continue
    result = subprocess.run(
        ["grep", "-rn", "except\\s*Exception\\s*:\\s*continue", "app/"],
        capture_output=True, text=True,
        cwd="/home/varv0id/projects/ML-Engineer-test"
    )
    assert result.returncode == 1 or result.stdout == "", f"Found except Exception: continue in: {result.stdout}"


# AC-9: full suite passes (prior 77 + new)
def test_rag_pipeline_resilience_full_suite():
    """Integration test: full RAG pipeline with resilience. Verify that the
    entire flow works with proper error handling and retries."""
    store = CountingFakeVectorStore()
    embedder = CountingFakeEmbeddingProvider()
    llm = CountingFakeLLMClient(response="The document mentions Margaret Thompson.")

    app.dependency_overrides[get_embedding] = lambda: embedder
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm

    client = TestClient(app)

    # Ingest
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()
    r = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["chunks_stored"] > 0

    # Ask
    r = client.post("/api/ask", json={"question": "Who attended the meeting?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "answer" in body
    assert "sources" in body
