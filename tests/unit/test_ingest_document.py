"""Ingest against an in-memory Qdrant: identity, skip, replace, no orphans."""

from collections.abc import Sequence
import hashlib

import qdrant_client

from app import config
from app.adapters.qdrant import vector_store as qdrant_store
from app.adapters.text_chunker import sentence
from app.domain import rag
from app.service_layer import ingest
from tests import builders
from tests.fakes import cpu_runner
from tests.fakes import embedding
from tests.fakes import ocr as ocr_fake
from tests.fakes import page_renderer as page_renderer_fake
from tests.fakes import sparse_embedding

BUDGET = "The board approved the laboratory budget for next year after a vote."
HIRING = "Anna Berg will lead hiring for the data team starting in March."
MEMO = [[BUDGET, "Revenue grew by ten percent in the last quarter."], [HIRING]]


async def empty_store() -> qdrant_store.QdrantVectorStore:
    """Returns a store backed by a fresh in-process Qdrant collection.

    Returns:
        The store, with its collection created.
    """
    store = qdrant_store.QdrantVectorStore(
        qdrant_client.AsyncQdrantClient(location=":memory:"),
        config.QdrantSettings(),
        collection="chunks_test",
        dimension=embedding.HashingEmbedding.DIMENSION,
    )
    await store.ensure_collection()
    return store


async def ingest_page(
    store: qdrant_store.QdrantVectorStore,
    document_key: str,
    pdf: bytes,
    blocks: Sequence[Sequence[str]],
) -> rag.IngestResult:
    """Ingests a one-page document whose OCR text is ``blocks``.

    Args:
        store: The vector store.
        document_key: Identity of the document.
        pdf: The PDF bytes; their hash is the content identity.
        blocks: The page's text blocks, each a list of lines.

    Returns:
        The ingest result.
    """
    use_case = ingest.IngestDocument(
        renderer=page_renderer_fake.BlankPageRenderer(1),
        ocr=ocr_fake.ScriptedOcr([builders.page_words(blocks)]),
        chunker=sentence.SentenceTextChunker(chunk_size=80, chunk_overlap=10),
        embedder=embedding.HashingEmbedding(),
        sparse_embedder=sparse_embedding.WordCountSparseEmbedding(),
        store=store,
        cpu=cpu_runner.InlineCpuRunner(),
    )
    return await use_case(pdf, document_key)


async def test_second_document_with_identical_content_keeps_the_first() -> None:
    store = await empty_store()

    first = await ingest_page(store, "memo.pdf", b"%PDF-1 memo", MEMO)
    second = await ingest_page(store, "copy.pdf", b"%PDF-1 memo", MEMO)

    documents = {
        d.document_key: d.chunk_count for d in await store.list_documents()
    }
    assert (first.status, second.status) == (rag.IngestStatus.INGESTED,) * 2
    assert documents == {
        "memo.pdf": first.chunks_stored,
        "copy.pdf": first.chunks_stored,
    }
    assert first.chunks_stored > 1
    hits = await store.hybrid_search(
        rag.SearchQuery(
            embedding.HashingEmbedding().embed_query(HIRING),
            sparse_embedding.WordCountSparseEmbedding().embed_query(HIRING),
        ),
        4,
    )
    assert {hit.chunk.document_key for hit in hits[:2]} == {
        "memo.pdf",
        "copy.pdf",
    }
    assert all(HIRING in hit.chunk.text for hit in hits[:2])


async def test_unchanged_content_under_the_same_key_is_skipped() -> None:
    store = await empty_store()
    first = await ingest_page(store, "memo.pdf", b"%PDF-1 memo", MEMO)

    again = await ingest_page(store, "memo.pdf", b"%PDF-1 memo", MEMO)

    record = await store.get_document("memo.pdf")
    assert again == rag.IngestResult(
        "memo.pdf", rag.IngestStatus.UNCHANGED, first.chunks_stored
    )
    assert record is not None and record.chunk_count == first.chunks_stored


async def test_changed_content_replaces_old_chunks_and_leaves_others() -> None:
    store = await empty_store()
    await ingest_page(store, "memo.pdf", b"%PDF-1 memo", MEMO)
    other = await ingest_page(store, "other.pdf", b"%PDF-1 other", [[BUDGET]])
    new_pdf = b"%PDF-1 memo v2"

    replaced = await ingest_page(store, "memo.pdf", new_pdf, [[HIRING]])

    memo = await store.get_document("memo.pdf")
    assert replaced == rag.IngestResult(
        "memo.pdf", rag.IngestStatus.REPLACED, 1
    )
    assert memo == rag.DocumentRecord(
        "memo.pdf", hashlib.sha256(new_pdf).hexdigest(), 1
    )
    assert await store.get_document("other.pdf") == rag.DocumentRecord(
        "other.pdf",
        hashlib.sha256(b"%PDF-1 other").hexdigest(),
        other.chunks_stored,
    )
