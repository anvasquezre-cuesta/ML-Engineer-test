import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.domain.chunking import Chunk
from app.domain.errors import VectorStoreUnavailable
from app.infrastructure.chroma_vector_store import ChromaVectorStore

pytestmark = pytest.mark.integration

MEMO = [Chunk("aaa", "memo.pdf", 0, 0, "memo first"), Chunk("aaa", "memo.pdf", 0, 1, "memo second")]
MINUTES = [Chunk("bbb", "minutes.pdf", 1, 0, "minutes text")]


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ChromaVectorStore]:
    store = ChromaVectorStore(str(tmp_path / "chroma"), "chunks")
    yield store
    store.close()


def test_chunks_round_trip_with_their_metadata(store: ChromaVectorStore) -> None:
    store.replace_document("aaa", MEMO, [[1.0, 0.0], [0.9, 0.1]])
    store.replace_document("bbb", MINUTES, [[0.0, 1.0]])

    assert sorted(store.all_chunks(), key=lambda c: c.id) == [*MEMO, *MINUTES]
    assert store.search([0.0, 1.0], 1) == MINUTES
    assert store.search([1.0, 0.0], 10)[0] == MEMO[0]


def test_replacing_a_document_drops_its_old_chunks_only(store: ChromaVectorStore) -> None:
    store.replace_document("aaa", MEMO, [[1.0, 0.0], [0.9, 0.1]])
    store.replace_document("bbb", MINUTES, [[0.0, 1.0]])

    store.replace_document("aaa", MEMO[:1], [[1.0, 0.0]])

    assert sorted(c.id for c in store.all_chunks()) == ["aaa:0", "bbb:0"]


def test_empty_store_returns_nothing(store: ChromaVectorStore) -> None:
    assert store.all_chunks() == []
    assert store.search([1.0, 0.0], 5) == []


def test_closing_releases_the_files_so_the_folder_can_be_deleted(tmp_path: Path) -> None:
    path = tmp_path / "chroma"
    store = ChromaVectorStore(str(path), "chunks")
    store.replace_document("aaa", MEMO, [[1.0, 0.0], [0.9, 0.1]])

    store.close()
    shutil.rmtree(path)  # Windows keeps HNSW files locked until the client is released

    assert not path.exists()


def test_chroma_never_downloads_its_default_embedding_model(store: ChromaVectorStore) -> None:
    store.replace_document("aaa", MEMO, [[1.0, 0.0], [0.9, 0.1]])
    store.search([1.0, 0.0], 1)

    assert not (Path.home() / ".cache" / "chroma" / "onnx_models").exists()


def test_vendor_errors_are_translated(store: ChromaVectorStore) -> None:
    store.replace_document("aaa", MEMO, [[1.0, 0.0], [0.9, 0.1]])

    with pytest.raises(VectorStoreUnavailable, match="search"):
        store.search([1.0, 0.0, 0.0], 1)  # wrong dimension
