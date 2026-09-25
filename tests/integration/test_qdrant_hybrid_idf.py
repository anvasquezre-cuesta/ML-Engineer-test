"""Hybrid search on a Qdrant server ranks the same after replaces and deletes.

Qdrant's server-side IDF can keep counting deleted points, so a collection
that went through document replaces and deletes must still rank exactly like
one built fresh from the documents it holds now.
"""

from collections.abc import AsyncIterator
import uuid

import pytest
import qdrant_client

from app import config
from app.adapters.qdrant import vector_store as qdrant_store
from app.domain import rag

pytestmark = [pytest.mark.integration, pytest.mark.docker]

Item = tuple[str, str, list[float], dict[int, float]]

KEPT: list[Item] = [
    ("a.pdf", "h1", [1.0, 0.0, 0.0, 0.0], {10: 1.0, 11: 1.0}),
    ("b.pdf", "h1", [0.0, 1.0, 0.0, 0.0], {10: 1.0, 12: 2.0}),
    ("c.pdf", "h1", [0.0, 0.0, 1.0, 0.0], {11: 1.0, 12: 1.0, 13: 1.0}),
]
REPLACED_OLD: Item = ("memo.pdf", "v1", [0.5, 0.5, 0.0, 0.0], {13: 3.0})
REPLACED_NEW: Item = (
    "memo.pdf",
    "v2",
    [0.0, 0.0, 0.5, 0.5],
    {12: 1.0, 14: 1.0},
)
REMOVED: list[Item] = [
    ("gone.pdf", "h1", [0.0, 0.0, 0.0, 1.0], {12: 1.0, 13: 1.0}),
    ("gone.pdf", "h1", [0.2, 0.2, 0.2, 0.2], {12: 1.0, 11: 1.0}),
]
QUERY = rag.SearchQuery(
    dense=(0.4, 0.3, 0.2, 0.1),
    sparse=rag.SparseVector((11, 12, 13, 14), (1.0, 1.0, 1.0, 1.0)),
)


def embedded(items: list[Item]) -> list[rag.EmbeddedChunk]:
    """Builds one embedded chunk per item, numbered within its document.

    Args:
        items: Document key, content hash, dense vector and term weights.

    Returns:
        The embedded chunks.
    """
    counts: dict[str, int] = {}
    chunks = []
    for key, content_hash, dense, sparse in items:
        index = counts.get(key, 0)
        counts[key] = index + 1
        chunk = rag.Chunk(key, content_hash, 0, index, 0, 1, key, "t")
        chunks.append(
            rag.EmbeddedChunk(
                chunk,
                tuple(dense),
                rag.SparseVector(tuple(sparse), tuple(sparse.values())),
            )
        )
    return chunks


@pytest.fixture
async def client() -> AsyncIterator[qdrant_client.AsyncQdrantClient]:
    """Yields a client for the compose Qdrant server.

    Yields:
        An async Qdrant client.
    """
    settings = config.QdrantSettings()
    api_key = settings.api_key.get_secret_value() if settings.api_key else None
    qdrant = qdrant_client.AsyncQdrantClient(
        url=settings.url, api_key=api_key, check_compatibility=False
    )
    try:
        yield qdrant
    finally:
        await qdrant.close()


async def test_ranking_after_replace_and_delete_matches_a_fresh_store(
    client: qdrant_client.AsyncQdrantClient,
) -> None:
    names = [f"test_hybrid_{uuid.uuid4().hex}" for _ in range(2)]
    churned, fresh = (
        qdrant_store.QdrantVectorStore(
            client, config.QdrantSettings(), collection=name, dimension=4
        )
        for name in names
    )
    try:
        await churned.upsert(embedded([*KEPT, REPLACED_OLD, *REMOVED]))
        await churned.delete_document("memo.pdf")
        await churned.upsert(embedded([REPLACED_NEW]))
        await churned.delete_document("gone.pdf")
        await fresh.upsert(embedded([*KEPT, REPLACED_NEW]))

        churned_hits = await churned.hybrid_search(QUERY, top_k=10)
        fresh_hits = await fresh.hybrid_search(QUERY, top_k=10)

        assert {h.chunk: round(h.score, 6) for h in churned_hits} == {
            h.chunk: round(h.score, 6) for h in fresh_hits
        }
    finally:
        for name in names:
            await client.delete_collection(name)
