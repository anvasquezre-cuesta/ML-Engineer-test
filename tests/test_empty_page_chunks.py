"""AC: empty-page chunks skipped (I/O & Edge-Case Matrix row 7).

Given a page with only whitespace, chunks are skipped by the
chunk.strip() guard in ingest_document, and no empty IDs are stored.
"""

import pytest
from app.services.rag_service import chunk_text
from app.services.embedding_service import EmbeddingProvider
from app.core.config import get_settings


class FixedVectorEmbedder(EmbeddingProvider):
    """Embedding wrapper returning fixed vectors — no model dependency."""
    def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class WhitespaceOcrProvider:
    """Stub OcrProvider whose pages OCR to only whitespace."""
    def ocr_page(self, raw, page_index, dpi):
        if page_index == 0:
            return "   ", None
        return "\n\t \n", None

    def page_count(self, raw):
        return 2


@pytest.fixture
def chroma_store(tmp_path):
    """Real ChromaStore in a temporary directory."""
    persist_dir = str(tmp_path / "chroma")
    from app.adapters.chroma_store import ChromaStore
    store = ChromaStore(persist_dir, "empty-page-test")
    return store


def test_chunk_text_empty_strings_are_blank():
    """chunk_text("", 500) and chunk_text("   ", 500) produce no non-blank chunks."""
    for text in ("", "   "):
        chunks = chunk_text(text, 500)
        # Every returned chunk is whitespace-only, so the ingest guard will skip all
        non_blank = [c for c in chunks if c.strip()]
        assert non_blank == [], (
            f"chunk_text({text!r}) produced non-blank chunks: {non_blank}")


def test_ingest_whitespace_only_pages_stores_nothing(chroma_store):
    """Through-ingest: pages that OCR to only whitespace store zero chunks."""
    embedder = FixedVectorEmbedder()
    ocr = WhitespaceOcrProvider()
    s = get_settings()

    # "PDF" bytes — the stub OcrProvider never actually reads them
    raw = b"fake-pdf-bytes"

    n = ingest_document(raw, ocr, s, embedder, chroma_store)
    assert n == 0

    # Store must be completely empty — no entries at all
    result = chroma_store.collection.get(include=[])
    assert result["ids"] == [], (
        f"Expected empty store, got {len(result['ids'])} entries: {result['ids']}")


def ingest_document(raw, ocr, settings, embedder, store):
    """Thin wrapper around the service's ingest_document for this test file."""
    from app.services.rag_service import ingest_document as real_ingest
    return real_ingest(raw, ocr, settings, embedder, store)
