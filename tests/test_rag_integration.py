"""Integration test: real full RAG path against sample PDFs.

Gated: skipped unless DIS_LLM_BASE_URL is set (endpoint needs no API key).
Exercises real OCR -> chunk -> embed (SentenceTransformer) -> store (Chroma)
-> retrieve -> LLM ask path with a tmp_path-backed chroma_dir that actually
takes effect (providers constructed from explicit values passed in).
"""

import os
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_embedding, get_llm, get_vector_store
from app.services.ocr_service import validate_and_read
from app.services.rag_service import compute_doc_id, chunk_text, ingest_document, generate_answer


@pytest.fixture
def chroma_dir(tmp_path):
    """Temporary chroma directory that is actually used by the test."""
    return tmp_path / ".chroma"


@pytest.fixture
def providers(chroma_dir):
    """Real providers for integration testing. Returns (embedder, store, llm)."""
    from app.core.config import get_settings
    from app.adapters.sentence_embeddings import Embedder
    from app.adapters.chroma_store import ChromaStore
    from app.adapters.langchain_llm import LangChainLlm

    settings = get_settings()
    settings.chroma_dir = str(chroma_dir)

    embedder = Embedder(settings.embedding_model)
    store = ChromaStore(str(chroma_dir), settings.chroma_collection)
    llm = LangChainLlm(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
        backoff_seconds=settings.llm_backoff_seconds,
        temperature=settings.llm_temperature,
    )
    return embedder, store, llm


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("DIS_LLM_BASE_URL"),
                    reason="DIS_LLM_BASE_URL not set — LLM endpoint unavailable")
def test_rag_full_path(providers, chroma_dir):
    """OCR real PDF -> chunk -> embed -> store -> retrieve -> ask LLM."""
    from app.core.config import get_settings
    from app.dependencies import get_ocr

    settings = get_settings()
    embedder, store, llm = providers
    ocr = get_ocr(settings)

    # Ingest a real sample PDF via the service layer
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        raw = f.read()
    chunk_count = ingest_document(raw, ocr, settings, embedder, store)
    assert chunk_count > 0, "Expected chunks to be stored"

    # Ask a question via the service layer
    result = generate_answer("Who attended the meeting?", embedder, store, llm, settings.top_k)
    assert isinstance(result["answer"], str) and len(result["answer"]) > 0
    # Sources come from retrieved chunks, not the LLM's answer
    for source in result["sources"]:
        assert isinstance(source, str) and len(source) > 0


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("DIS_LLM_BASE_URL"),
                    reason="DIS_LLM_BASE_URL not set — LLM endpoint unavailable")
def test_rag_endpoints_via_http(providers, chroma_dir):
    """POST /api/ingest then /api/ask through the HTTP layer."""
    embedder, store, llm = providers
    app.dependency_overrides[get_embedding] = lambda: embedder
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        client = TestClient(app)

        with open("sample_pdfs/company_memo.pdf", "rb") as f:
            pdf = f.read()
        r = client.post("/api/ingest", files={"file": ("memo.pdf", pdf, "application/pdf")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["chunks_stored"] > 0

        r = client.post("/api/ask", json={"question": "Who attended the meeting?"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body["answer"], str) and len(body["answer"]) > 0
        for source in body["sources"]:
            assert isinstance(source, str) and len(source) > 0
    finally:
        app.dependency_overrides.clear()
