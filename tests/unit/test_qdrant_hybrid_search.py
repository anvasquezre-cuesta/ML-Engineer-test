"""Hybrid search on an in-memory Qdrant: exact terms count, not only meaning."""

import pytest
import qdrant_client

from app import config
from app.adapters.qdrant import vector_store as qdrant_store
from app.domain import rag

pytestmark = pytest.mark.xfail(
    strict=True, raises=NotImplementedError, reason="hybrid search not built"
)

TERMS = {"thomas": 1, "muller": 2, "board": 3, "chief": 4, "officer": 5}
SAME_MEANING = (1.0, 0.0, 0.0, 0.0)


def terms(*words: str) -> rag.SparseVector:
    """Builds term weights with one count per word.

    Args:
        *words: Words present in the text.

    Returns:
        The sparse vector.
    """
    return rag.SparseVector(
        indices=tuple(TERMS[w] for w in words), values=(1.0,) * len(words)
    )


def chunk(index: int, text: str) -> rag.Chunk:
    """Builds a page-0 chunk of ``minutes.pdf``.

    Args:
        index: Chunk position on the page.
        text: Chunk text.

    Returns:
        The chunk.
    """
    return rag.Chunk("minutes.pdf", "h", 0, index, 0, len(text), text, "t")


async def test_rare_exact_name_wins_when_dense_vectors_cannot_rank() -> None:
    store = qdrant_store.QdrantVectorStore(
        qdrant_client.AsyncQdrantClient(location=":memory:"),
        config.QdrantSettings(),
        collection="chunks_test",
        dimension=len(SAME_MEANING),
    )
    await store.upsert(
        [
            rag.EmbeddedChunk(
                chunk(0, "The board met."), SAME_MEANING, terms("board")
            ),
            rag.EmbeddedChunk(
                chunk(1, "Chief officer report."),
                SAME_MEANING,
                terms("chief", "officer"),
            ),
            rag.EmbeddedChunk(
                chunk(2, "Thomas Muller, Chief Technology Officer."),
                SAME_MEANING,
                terms("thomas", "muller", "chief", "officer"),
            ),
        ]
    )

    hits = await store.hybrid_search(
        rag.SearchQuery(SAME_MEANING, terms("muller")), top_k=3
    )

    assert hits[0].chunk.chunk_index == 2
