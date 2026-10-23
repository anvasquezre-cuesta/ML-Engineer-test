"""The real Chroma adapter (no network, no models).

In-process Chroma clients share state, so every test gets its own collection.
"""

import uuid
from pathlib import Path

import chromadb
import pytest

from app.adapters.chroma_store import ChromaVectorStore
from app.core.config import RAGSettings
from app.domain.models import Chunk

pytestmark = pytest.mark.integration


def _store() -> ChromaVectorStore:
    return ChromaVectorStore(chromadb.EphemeralClient(), f"test-{uuid.uuid4().hex}")


def _chunks(doc_id: str, pages: int, filename: str = "a.pdf") -> list[Chunk]:
    return [
        Chunk(doc_id, filename, page, 0, f"text of {doc_id} page {page}") for page in range(pages)
    ]


def _unit(i: int, dims: int = 8) -> list[float]:
    return [1.0 if j == i % dims else 0.0 for j in range(dims)]


def test_two_documents_are_both_stored() -> None:
    store = _store()

    store.replace_document("doc-a", _chunks("doc-a", 3), [_unit(i) for i in range(3)])
    store.replace_document("doc-b", _chunks("doc-b", 2), [_unit(i) for i in range(2)])

    assert store.count() == 5


def test_same_document_twice_leaves_the_count_unchanged() -> None:
    store = _store()

    store.replace_document("doc-a", _chunks("doc-a", 3), [_unit(i) for i in range(3)])
    store.replace_document("doc-a", _chunks("doc-a", 3), [_unit(i) for i in range(3)])

    assert store.count() == 3


def test_reingest_with_fewer_chunks_prunes_the_stale_ones() -> None:
    store = _store()
    store.replace_document("doc-a", _chunks("doc-a", 3), [_unit(i) for i in range(3)])

    store.replace_document("doc-a", _chunks("doc-a", 1), [_unit(0)])

    assert store.count() == 1


def test_query_returns_chunks_and_metadata_most_similar_first() -> None:
    store = _store()
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
    assert all(0.0 <= r.similarity <= 1.0 for r in results)


def test_opposite_vectors_have_zero_similarity_not_negative() -> None:
    store = _store()
    store.replace_document("doc-a", _chunks("doc-a", 1), [[1.0, 0.0]])

    (result,) = store.query([-1.0, 0.0], top_k=1)

    assert result.similarity == 0.0


def test_data_survives_a_restart(tmp_path: Path) -> None:
    settings = RAGSettings(chroma_path=str(tmp_path / "chroma"), collection="docs")
    ChromaVectorStore.persistent(settings).replace_document(
        "doc-a", _chunks("doc-a", 2), [_unit(0), _unit(1)]
    )

    assert ChromaVectorStore.persistent(settings).count() == 2


def test_mismatched_chunks_and_vectors_are_rejected() -> None:
    with pytest.raises(ValueError):
        _store().replace_document("doc-a", _chunks("doc-a", 2), [_unit(0)])
