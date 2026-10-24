"""Chunk identity and multi-document ingest tests.

Given three sample PDFs ingested into a shared real Chroma store with real
OCR and fixed-vector embeddings, verify: all three doc_ids appear as
disjoint prefixes, total chunk count equals the sum of the three ingest
returns, and every stored chunk tokenizes to a contiguous word subsequence
of its source page.

Also verify compute_doc_id determinism and format.
"""

import pytest
from app.services.rag_service import compute_doc_id, ingest_document
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
    store = ChromaStore(persist_dir, "chunk-identity-test")
    return store


def is_contiguous_token_subsequence(chunk_text: str, page_text: str) -> bool:
    """Check that the chunk's whitespace tokens form a contiguous subsequence
    of the page's whitespace tokens (i.e., no mid-word cuts)."""
    page_tokens = page_text.split()
    chunk_tokens = chunk_text.split()
    if not chunk_tokens:
        return True
    # Slide a window of chunk_tokens length over page_tokens
    for i in range(len(page_tokens) - len(chunk_tokens) + 1):
        if page_tokens[i:i + len(chunk_tokens)] == chunk_tokens:
            return True
    return False


def test_ingest_all_three_sample_pdfs(chroma_store):
    """Three PDFs → three disjoint doc_id prefixes; chunks are contiguous word sequences."""
    embedder = FixedVectorEmbedder()
    ocr = OcrProvider()
    s = get_settings()

    pdf_paths = [
        "sample_pdfs/company_memo.pdf",
        "sample_pdfs/meeting_minutes.pdf",
        "sample_pdfs/research_report.pdf",
    ]

    # Load and compute doc_ids
    raws = []
    doc_ids = []
    for path in pdf_paths:
        with open(path, "rb") as f:
            raw = f.read()
        raws.append(raw)
        doc_ids.append(compute_doc_id(raw))

    # Verify all three doc_ids are distinct
    assert len(set(doc_ids)) == 3

    # Ingest all three
    ingest_counts = []
    for raw in raws:
        count = ingest_document(raw, ocr, s, embedder, chroma_store)
        ingest_counts.append(count)

    # All ingests should produce at least one chunk
    for count in ingest_counts:
        assert count > 0

    expected_total = sum(ingest_counts)

    # Check stored IDs
    all_ids = chroma_store.collection.get(include=[])["ids"]
    assert len(all_ids) == expected_total, f"Expected {expected_total} chunks, got {len(all_ids)}"

    # Verify disjoint prefixes
    prefix_sets = []
    for doc_id in doc_ids:
        prefix_set = set(i for i in all_ids if i.startswith(doc_id))
        prefix_sets.append(prefix_set)

    for i in range(3):
        for j in range(i + 1, 3):
            overlap = prefix_sets[i] & prefix_sets[j]
            assert not overlap, f"Doc {i} and doc {j} have overlapping ID prefixes: {overlap}"

    # Verify chunk identity: each chunk is a contiguous token subsequence of its source page
    get_results = chroma_store.collection.get(include=["documents", "metadatas"])
    chunk_texts = get_results["documents"]
    chunk_metas = get_results["metadatas"]

    for text, meta in zip(chunk_texts, chunk_metas):
        doc_id = meta["doc_id"]
        page_index = meta["page"]
        # Find which raw bytes correspond to this doc_id
        raw = None
        for i, did in enumerate(doc_ids):
            if did == doc_id:
                raw = raws[i]
                break
        assert raw is not None, f"Could not find raw bytes for doc_id {doc_id}"

        # Re-OCR the page to get source text
        page_text, _ = ocr.ocr_page(raw, page_index, s.ocr_dpi)

        # Verify chunk is a contiguous subsequence of the page's tokens
        assert is_contiguous_token_subsequence(text, page_text), (
            f"Chunk not a contiguous token subsequence of page {page_index} in doc {doc_id[:8]}...: "
            f"chunk={text[:50]!r}"
        )


def test_doc_id_determinism_and_format():
    """compute_doc_id is deterministic, content-sensitive, and has correct format."""
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        raw1 = f.read()

    # Same bytes → same ID
    id1 = compute_doc_id(raw1)
    id1_again = compute_doc_id(raw1)
    assert id1 == id1_again

    # Different bytes → different ID
    with open("sample_pdfs/meeting_minutes.pdf", "rb") as f:
        raw2 = f.read()
    id2 = compute_doc_id(raw2)
    assert id1 != id2

    # Format: 12 hex characters
    assert len(id1) == 12
    for char in id1:
        assert char in "0123456789abcdef", f"Non-hex char in doc_id: {char}"