"""Tracer bullet: ingest one document, ask one question (story 2.1).

Tests the RAG pipeline endpoints with fake provider implementations
to validate the protocol contracts and error handling without external
service dependencies.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_embedding, get_vector_store, get_llm
from app.services.embedding_service import EmbeddingProvider
from app.services.vector_service import VectorStore
from app.services.rag_service import LLMClient

# Fake embedding provider: returns fixed vectors
class FakeEmbeddingProvider(EmbeddingProvider):
    def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]

# Fake vector store: in-memory list
class FakeVectorStore(VectorStore):
    """In-memory vector store with ID-dedup (mimics Chroma upsert)."""
    def __init__(self):
        self._data = {}

    def add_chunks(self, ids, embeddings, documents, metadatas):
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

# Fake LLM client: returns a predictable response or raises
class FakeLLMClient(LLMClient):
    def __init__(self, response="The document mentions Margaret Thompson and Robert Chen.", error=None):
        self.response = response
        self.error = error

    def complete(self, prompt):
        if self.error:
            raise self.error
        return self.response

@pytest.fixture(autouse=True)
def override_deps():
    embedder = FakeEmbeddingProvider()
    store = FakeVectorStore()
    llm = FakeLLMClient()
    app.dependency_overrides[get_embedding] = lambda: embedder
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm
    yield
    app.dependency_overrides.clear()

@pytest.fixture
def client():
    return TestClient(app)

# AC1: Happy path ingest returns ok with chunks > 0
def test_ingest_valid_pdf_returns_ok_with_chunks(client):
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()
    r = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["chunks_stored"] > 0

# AC2: Chunks are word-boundary (don't cut words in half)
def test_chunks_are_word_boundary():
    """Verify chunking splits on word boundaries, never within a word."""
    from app.services.rag_service import chunk_text
    text = "The quick brown fox jumps over the lazy dog. " * 3
    chunks = chunk_text(text, chunk_size=30)
    original_words = set(text.split())
    for chunk in chunks:
        for word in chunk.split():
            assert word in original_words, f"Chunk has subword fragment: '{word}'"

# AC3: Idempotent re-ingest
def test_reingest_same_pdf_is_idempotent(client):
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()
    r1 = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    assert r1.status_code == 200
    store = app.dependency_overrides[get_vector_store]()
    ids_before = len(store.ids)
    r2 = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    assert r2.status_code == 200
    assert len(store.ids) == ids_before

# AC4: Two distinct docs have unique IDs
def test_two_docs_unique_ids_both_retrievable(client):
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf1 = f.read()
    with open("sample_pdfs/meeting_minutes.pdf", "rb") as f:
        pdf2 = f.read()
    r1 = client.post("/api/ingest", files={"file": ("memo.pdf", pdf1, "application/pdf")})
    assert r1.status_code == 200
    store = app.dependency_overrides[get_vector_store]()
    ids_before = len(store.ids)
    r2 = client.post("/api/ingest", files={"file": ("minutes.pdf", pdf2, "application/pdf")})
    assert r2.status_code == 200
    assert len(store.ids) > ids_before
    assert len(set(store.ids)) == len(store.ids)

# AC5: Grounded answer with sources
def test_ask_grounded_answer_cites_sources(client):
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()
    r = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    assert r.status_code == 200
    store = app.dependency_overrides[get_vector_store]()
    r = client.post("/api/ask", json={"question": "Who attended the meeting?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["sources"]) > 0
    retrieved_texts = store.documents
    for source in body["sources"]:
        assert any(source in doc for doc in retrieved_texts), f"Source not from retrieved chunks: {source}"

# AC6: Empty retrieval abstains
def test_ask_empty_retrieval_abstains(client):
    r = client.post("/api/ask", json={"question": "Who attended the meeting?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sources"] == []
    assert "no relevant" in body["answer"].lower() or "no" in body["answer"].lower() or "does not" in body["answer"].lower()

# AC7: Question length validation
def test_ask_invalid_question_length(client):
    r = client.post("/api/ask", json={"question": ""})
    assert r.status_code == 422, r.text
    r = client.post("/api/ask", json={"question": "x" * 2001})
    assert r.status_code == 422, r.text

# AC8: LLM error returns 502
def test_ask_llm_error_returns_502():
    # Use shared instances so ingest and ask hit the same store
    store = FakeVectorStore()
    embedder = FakeEmbeddingProvider()
    error_client = FakeLLMClient(error=RuntimeError("LLM call failed"))
    app.dependency_overrides[get_embedding] = lambda: embedder
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: error_client

    client = TestClient(app)
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()
    r = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
    assert r.status_code == 200

    r = client.post("/api/ask", json={"question": "Who attended the meeting?"})
    assert r.status_code == 502, r.text
    assert "detail" in r.json()

# AC9: Upload validation on ingest (not-PDF)
def test_ingest_not_pdf(client):
    r = client.post("/api/ingest", files={"file": ("notpdf.txt", b"hello", "text/plain")})
    assert r.status_code in (422, 400)
    assert "detail" in r.json()

# AC9: Upload validation on ingest (empty)
def test_ingest_empty(client):
    r = client.post("/api/ingest", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert r.status_code in (422, 400)
    assert "detail" in r.json()

# AC9: Upload validation on ingest (oversized)
def test_ingest_oversized(client):
    r = client.post("/api/ingest", files={"file": ("huge.pdf", b"%PDF-1.4" + b"\x00" * 25_000_000, "application/pdf")})
    assert r.status_code in (413, 400)
    assert "detail" in r.json()