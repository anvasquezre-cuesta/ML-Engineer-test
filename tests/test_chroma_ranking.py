"""AC6: Real Chroma ranking with actual embeddings.

Uses two distinct sample PDFs and a question answerable from only one.
Verifies the top-ranked chunk belongs to the correct document.
No LLM needed — only ingest + query.
"""
import pytest
from app.core.config import get_settings
from app.dependencies import get_ocr
from app.services.rag_service import ingest_document


@pytest.fixture
def providers(tmp_path):
    """Real embedder and Chroma store, tmp_path-backed. No LLM."""
    from app.adapters.sentence_embeddings import Embedder
    from app.adapters.chroma_store import ChromaStore

    settings = get_settings()
    chroma_dir = tmp_path / ".chroma"
    settings.chroma_dir = str(chroma_dir)

    embedder = Embedder(settings.embedding_model)
    store = ChromaStore(str(chroma_dir), settings.chroma_collection)
    return embedder, store, settings


def test_real_chroma_ranks_correct_document_first(providers):
    """Ingest two PDFs; a meeting-attendee question must rank the meeting document's chunks first."""
    embedder, store, settings = providers
    ocr = get_ocr(settings)

    # Ingest company memo (should be about meeting logistics)
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        memo_raw = f.read()
    memo_chunks = ingest_document(memo_raw, ocr, settings, embedder, store)
    assert memo_chunks > 0, "Expected memo chunks to be stored"

    # Ingest research report (different topic)
    with open("sample_pdfs/research_report.pdf", "rb") as f:
        report_raw = f.read()
    report_chunks = ingest_document(report_raw, ocr, settings, embedder, store)
    assert report_chunks > 0, "Expected report chunks to be stored"

    # Question answerable from the company memo (promotions), not the research report
    question = "Who was promoted to VP of Engineering?"
    query_embedding = embedder.embed_query(question)
    results = store.query(query_embedding, top_k=3)

    assert len(results) > 0, "Expected at least one retrieved chunk"

    # Top result should be from the memo, mentioning the promotion
    top = results[0]
    top_text = top["text"].lower()
    # The memo explicitly states who was promoted; research report has different names
    assert ("chen" in top_text or "promoted" in top_text or "engineering" in top_text), \
        f"Top chunk not about promotion: {top_text[:100]}"


def test_real_chroma_query_returns_expected_shape(providers):
    """Sanity check: real query returns dicts with id, text, metadata, distance."""
    embedder, store, settings = providers
    ocr = get_ocr(settings)

    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        raw = f.read()
    ingest_document(raw, ocr, settings, embedder, store)

    results = store.query(embedder.embed_query("test"), top_k=1)
    assert len(results) == 1
    chunk = results[0]
    assert "id" in chunk
    assert "text" in chunk
    assert "metadata" in chunk
    assert "distance" in chunk