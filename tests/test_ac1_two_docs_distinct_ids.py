"""AC1: Two different PDFs ingested into the same real Chroma store.

Given two different sample PDFs ingested into the same real Chroma store,
when the second ingest completes,
then both documents' chunks remain present and their doc_id ID prefixes
are disjoint.
"""

import pytest
from app.services.rag_service import compute_doc_id
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
    store = ChromaStore(persist_dir, "ac1-test")
    return store


def ingest_document(raw, ocr, settings, embedder, store):
    """Thin wrapper around ingest_document for this test file."""
    from app.services.rag_service import ingest_document as real_ingest
    return real_ingest(raw, ocr, settings, embedder, store)


def test_two_pdf_docs_have_disjoint_id_prefixes(chroma_store):
    """Both PDFs present, doc_id prefixes disjoint."""
    embedder = FixedVectorEmbedder()
    ocr = OcrProvider()
    s = get_settings()

    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        memo_raw = f.read()
    with open("sample_pdfs/meeting_minutes.pdf", "rb") as f:
        minutes_raw = f.read()

    memo_id = compute_doc_id(memo_raw)
    minutes_id = compute_doc_id(minutes_raw)
    assert memo_id != minutes_id

    n1 = ingest_document(memo_raw, ocr, s, embedder, chroma_store)
    n2 = ingest_document(minutes_raw, ocr, s, embedder, chroma_store)
    assert n1 > 0
    assert n2 > 0

    # All IDs should be prefixed by one of the two doc_ids, no overlap
    all_ids = chroma_store.collection.get(include=[])["ids"]
    memo_ids = [i for i in all_ids if i.startswith(memo_id)]
    minutes_ids = [i for i in all_ids if i.startswith(minutes_id)]
    assert len(memo_ids) == n1
    assert len(minutes_ids) == n2
    # No overlap between the two sets
    assert not (set(memo_ids) & set(minutes_ids))