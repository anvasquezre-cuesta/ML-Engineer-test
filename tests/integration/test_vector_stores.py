"""One contract, two stores: every test runs against Chroma and Qdrant (roadmap F17).

Both run in-process (no server, no network): Chroma's ephemeral client with a
fresh collection per test (in-process Chroma clients share state), and Qdrant's
``:memory:`` mode. Persistence uses each store's on-disk mode.
"""

import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import chromadb
import pytest
from qdrant_client import QdrantClient

from app.adapters.chroma_store import ChromaVectorStore
from app.adapters.qdrant_store import QdrantVectorStore
from app.core.config import RAGSettings
from app.domain.models import Chunk
from app.domain.protocols import VectorStore

pytestmark = pytest.mark.integration

BACKENDS = ["chroma", "qdrant"]


@pytest.fixture(params=BACKENDS)
def store(request: pytest.FixtureRequest) -> Iterator[VectorStore]:
    if request.param == "chroma":
        yield ChromaVectorStore(chromadb.EphemeralClient(), f"test-{uuid.uuid4().hex}")
    else:
        qdrant = QdrantVectorStore(QdrantClient(":memory:"), "test")
        yield qdrant
        qdrant.close()


def _chunks(doc_id: str, pages: int, filename: str = "a.pdf") -> list[Chunk]:
    return [
        Chunk(doc_id, filename, page, 0, f"text of {doc_id} page {page}") for page in range(pages)
    ]


def _unit(i: int, dims: int = 8) -> list[float]:
    return [1.0 if j == i % dims else 0.0 for j in range(dims)]


def test_two_documents_are_both_stored(store: VectorStore) -> None:
    store.replace_document("doc-a", _chunks("doc-a", 3), [_unit(i) for i in range(3)])
    store.replace_document("doc-b", _chunks("doc-b", 2), [_unit(i) for i in range(2)])

    assert store.count() == 5


def test_same_document_twice_leaves_the_count_unchanged(store: VectorStore) -> None:
    store.replace_document("doc-a", _chunks("doc-a", 3), [_unit(i) for i in range(3)])
    store.replace_document("doc-a", _chunks("doc-a", 3), [_unit(i) for i in range(3)])

    assert store.count() == 3


def test_reingest_with_fewer_chunks_prunes_the_stale_ones(store: VectorStore) -> None:
    store.replace_document("doc-a", _chunks("doc-a", 3), [_unit(i) for i in range(3)])
    store.replace_document("doc-b", _chunks("doc-b", 1), [_unit(5)])

    store.replace_document("doc-a", _chunks("doc-a", 1), [_unit(0)])

    assert store.count() == 2  # doc-a pruned to 1, doc-b untouched


def test_query_returns_chunks_and_metadata_most_similar_first(store: VectorStore) -> None:
    store.replace_document("doc-a", _chunks("doc-a", 3, "memo.pdf"), [_unit(i) for i in range(3)])

    results = store.query(_unit(1), top_k=2)

    best = results[0]
    assert best.chunk.page == 1
    assert (best.chunk.doc_id, best.chunk.filename, best.chunk.chunk_index) == (
        "doc-a",
        "memo.pdf",
        0,
    )
    assert best.chunk.text == "text of doc-a page 1"
    assert best.similarity == pytest.approx(1.0)
    assert len(results) == 2
    assert all(0.0 <= r.similarity <= 1.0 for r in results)


def test_opposite_vectors_have_zero_similarity_not_negative(store: VectorStore) -> None:
    store.replace_document("doc-a", _chunks("doc-a", 1), [[1.0, 0.0]])

    (result,) = store.query([-1.0, 0.0], top_k=1)

    assert result.similarity == 0.0


def test_an_empty_store_answers_queries_and_counts(store: VectorStore) -> None:
    assert store.count() == 0
    assert store.query(_unit(0), top_k=3) == []


def test_a_document_without_text_on_an_empty_store_stores_nothing(store: VectorStore) -> None:
    assert store.replace_document("blank", [], []) == 0
    assert store.count() == 0


def test_mismatched_chunks_and_vectors_are_rejected(store: VectorStore) -> None:
    with pytest.raises(ValueError):
        store.replace_document("doc-a", _chunks("doc-a", 2), [_unit(0)])


Reopen = Callable[[Path], tuple[VectorStore, Callable[[], None]]]


def _chroma_on_disk(path: Path) -> tuple[VectorStore, Callable[[], None]]:
    rag = RAGSettings(chroma_path=str(path / "chroma"), collection="docs")
    return ChromaVectorStore.persistent(rag), lambda: None


def _qdrant_on_disk(path: Path) -> tuple[VectorStore, Callable[[], None]]:
    rag = RAGSettings(vector_store="qdrant", qdrant_path=str(path / "qdrant"), collection="docs")
    store = QdrantVectorStore.from_settings(rag)
    return store, store.close  # embedded Qdrant locks its directory until closed


@pytest.mark.parametrize("reopen", [_chroma_on_disk, _qdrant_on_disk], ids=BACKENDS)
def test_data_survives_a_restart(tmp_path: Path, reopen: Reopen) -> None:
    first, close = reopen(tmp_path)
    first.replace_document("doc-a", _chunks("doc-a", 2), [_unit(0), _unit(1)])
    close()

    second, close_again = reopen(tmp_path)
    assert second.count() == 2
    close_again()
