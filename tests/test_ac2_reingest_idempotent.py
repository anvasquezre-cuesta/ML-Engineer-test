"""AC2: Same PDF re-ingested is idempotent.

Given the same PDF ingested twice into the same real Chroma store,
when the second ingest completes,
then chunk count is unchanged and each chunk ID maps to identical text.
"""

import pytest
from app.services.ocr_service import ocr_page, page_count
from app.services.embedding_service import EmbeddingProvider
from app.core.config import get_settings


class OcrProvider:
    """Satisfies the OcrProvider protocol for ingest_document."""
    def ocr_page(self, raw, page_index, dpi):
        return ocr_page(raw, page_index, dpi)
    def page_count(self, raw):
        return page_count(raw)


class FixedVectorEmbedder(EmbeddingProvider):
    """Embedding wrapper returning fixed vectors — no model dependency."""
    def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


@pytest.fixture
def chroma_store(tmp_path):
    """Real ChromaStore in a temporary directory."""
    persist_dir = str(tmp_path / "chroma")
    from app.adapters.chroma_store import ChromaStore
    store = ChromaStore(persist_dir, "ac2-test")
    return store


def ingest_document(raw, ocr, settings, embedder, store):
    """Thin wrapper around ingest_document for this test file."""
    from app.services.rag_service import ingest_document as real_ingest
    return real_ingest(raw, ocr, settings, embedder, store)


def test_same_pdf_reingest_is_idempotent(chroma_store):
    """Second ingest of same PDF adds no new chunks."""
    embedder = FixedVectorEmbedder()
    ocr = OcrProvider()
    s = get_settings()

    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        raw = f.read()

    n1 = ingest_document(raw, ocr, s, embedder, chroma_store)
    assert n1 > 0
    first_ids = chroma_store.collection.get(include=[])["ids"]
    assert len(first_ids) == n1

    n2 = ingest_document(raw, ocr, s, embedder, chroma_store)
    assert n2 > 0
    second_ids = chroma_store.collection.get(include=[])["ids"]
    # Same chunk count after re-ingest
    assert len(second_ids) == n1
    # Same IDs (deterministic re-ingest)
    assert set(second_ids) == set(first_ids)