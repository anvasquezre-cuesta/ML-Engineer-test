"""Closing e2e suite: extract-to-ask through the real app (story 2.3).

Real app, real OCR/NER, real embedder, real Chroma — only the LLM is stubbed
(a fake LLMClient injected via dependency_overrides). One test walks the full
surface: /api/extract -> /api/ingest -> /api/ask.
"""

import pytest
from fastapi.testclient import TestClient
from tempfile import TemporaryDirectory

from app.main import app
from app.dependencies import get_llm, get_embedding, get_vector_store
from app.services.rag_service import LLMClient


def build_stub_llm(answer: str = "Robert Chen attended the meeting as CFO.",
                  call_count: list = None) -> LLMClient:
    """Stub LLM that returns a fixed, grounded answer."""
    class StubLlm(LLMClient):
        def complete(self, prompt: str) -> str:
            if call_count is not None:
                call_count.append(prompt)
            return answer
    return StubLlm()


@pytest.fixture
def tmp_chroma():
    """Temp chroma directory for isolation between tests."""
    with TemporaryDirectory() as d:
        yield d


@pytest.fixture
def e2e_client(tmp_chroma):
    """Real app with only LLM stubbed; all other providers are real.

    Override get_llm (to stub) and get_vector_store (to tmp chroma).
    get_embedding uses the real Embedder. Cleanup restores defaults.
    """
    from app.core.config import get_settings
    from app.adapters.chroma_store import ChromaStore

    stub = build_stub_llm()
    settings = get_settings()

    app.dependency_overrides[get_llm] = lambda: stub
    app.dependency_overrides[get_vector_store] = (
        lambda: ChromaStore(tmp_chroma, settings.chroma_collection)
    )

    yield TestClient(app)

    app.dependency_overrides.clear()


def test_extract_ingest_ask_through_real_app(e2e_client, tmp_chroma):
    """AC-1: e2e happy path — extract names, ingest, ask question.

    Real OCR, real NER, real embedder, real Chroma, stub LLM only.
    """
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf_bytes = f.read()

    # Step 1: extract names with bounding boxes
    r_extract = e2e_client.post(
        "/api/extract",
        files={"file": ("memo.pdf", pdf_bytes, "application/pdf")},
        data={"names_json": "[]"},
    )
    assert r_extract.status_code == 200, r_extract.text
    extract_body = r_extract.json()
    names = extract_body.get("extracted_names", [])
    assert len(names) >= 1, f"Expected ≥1 name, got: {extract_body}"
    # Box should be in PDF point space (0-612, 0-792) on page 0
    box = names[0]["bounding_box"]
    assert box["page_number"] == 0
    assert 0 < box["x"] < 612
    assert 0 < box["y"] < 792

    # Step 2: ingest the same document into the vector store
    r_ingest = e2e_client.post(
        "/api/ingest",
        files={"file": ("memo.pdf", pdf_bytes, "application/pdf")},
    )
    assert r_ingest.status_code == 200, r_ingest.text
    ingest_body = r_ingest.json()
    assert ingest_body["status"] == "ok"
    assert ingest_body["chunks_stored"] > 0

    # Step 3: ask a grounded question
    r_ask = e2e_client.post("/api/ask", json={"question": "Who attended the meeting?"})
    assert r_ask.status_code == 200, r_ask.text
    ask_body = r_ask.json()
    assert isinstance(ask_body["answer"], str)
    assert len(ask_body["answer"]) > 0
    # Sources must be non-empty chunk texts
    sources = ask_body["sources"]
    assert len(sources) > 0, "Expected retrieved sources"
    for src in sources:
        assert isinstance(src, str)
        assert len(src) > 0, "Source should be non-empty chunk text"


def test_ask_sources_are_retrieved_chunk_texts(e2e_client, tmp_chroma):
    """AC-2: sources returned by /api/ask are actual chunk texts from the store."""
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf_bytes = f.read()

    # Ingest
    r_ingest = e2e_client.post(
        "/api/ingest",
        files={"file": ("memo.pdf", pdf_bytes, "application/pdf")},
    )
    assert r_ingest.status_code == 200, r_ingest.text
    ingest_body = r_ingest.json()
    assert ingest_body["chunks_stored"] > 0

    # Ask and verify sources are real chunk texts, not LLM-invented
    r_ask = e2e_client.post("/api/ask", json={"question": "Who attended the meeting?"})
    assert r_ask.status_code == 200, r_ask.text
    ask_body = r_ask.json()
    sources = ask_body["sources"]

    # Verify at least one source contains content from the document
    # (a word that would only appear if the LLM read actual chunks)
    found_real_source = False
    for src in sources:
        if any(word in src for word in ["Robert", "Chen", "Alice", "meeting", "CFO", "CEO", "Q1"]):
            found_real_source = True
            break
    assert found_real_source, (
        "Sources do not contain document-specific content; "
        "likely LLM-invented tokens rather than retrieved chunks"
    )
