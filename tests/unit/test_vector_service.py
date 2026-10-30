import random

import pytest
from chromadb.errors import ChromaError

from app.config import get_settings
from app.services.vector_service import (
    VectorStoreError,
    _collection,
    init_collection,
    search_similar,
    store_document_chunks,
)


class FakeEmbedder:
    """Deterministic 384-d unit vectors derived from the text; counts calls."""

    def __init__(self):
        self.calls = 0

    def __call__(self, texts):
        self.calls += 1
        vectors = []
        for text in texts:
            rng = random.Random(text)
            v = [rng.gauss(0, 1) for _ in range(384)]
            norm = sum(x * x for x in v) ** 0.5
            vectors.append([x / norm for x in v])
        return vectors


def store(doc_id, texts, embed):
    metadata = [
        {"doc_id": doc_id, "filename": f"{doc_id}.pdf", "page": 0, "chunk": i}
        for i in range(len(texts))
    ]
    store_document_chunks(texts, metadata, embed)


def test_ac_vec_01_two_documents_do_not_collide(chroma):
    embed = FakeEmbedder()
    store("a", ["alpha"], embed)
    store("b", ["beta"], embed)
    col = _collection()
    assert col.count() == 2
    assert sorted(col.get(ids=["a:0:0", "b:0:0"])["ids"]) == ["a:0:0", "b:0:0"]


def test_ac_vec_02_reingest_replaces_only_that_document(chroma):
    embed = FakeEmbedder()
    store("a", ["old 0", "old 1", "old 2"], embed)
    store("b", ["other"], embed)
    store("a", ["new 0", "new 1"], embed)
    col = _collection()
    a = col.get(where={"doc_id": "a"})
    assert dict(zip(a["ids"], a["documents"], strict=True)) == {
        "a:0:0": "new 0",
        "a:0:1": "new 1",
    }
    assert col.get(where={"doc_id": "b"})["documents"] == ["other"]


def test_ac_vec_03_search_returns_cosine_score_and_metadata(chroma):
    embed = FakeEmbedder()
    store("a", ["text x", "text y"], embed)
    vx, vy = embed(["text x", "text y"])
    first, second = search_similar(vx, top_k=2)
    assert first["text"] == "text x"
    assert first["score"] == pytest.approx(1.0, abs=1e-6)
    assert (first["filename"], first["page"], first["chunk"]) == ("a.pdf", 0, 0)
    assert second["score"] == pytest.approx(
        sum(x * y for x, y in zip(vx, vy, strict=True)), abs=1e-6
    )


@pytest.mark.parametrize("case", ["file-as-path", "other-model"])
def test_ac_vec_04_unusable_store_is_vector_store_error(
    chroma, tmp_path, monkeypatch, case
):
    if case == "file-as-path":
        (tmp_path / "file").write_text("not a folder")
        monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "file"))
    else:
        init_collection()
        monkeypatch.setenv("EMBEDDING_MODEL", "other-model")
        _collection.cache_clear()
    get_settings.cache_clear()
    with pytest.raises(VectorStoreError) as raised:
        init_collection()
    if case == "file-as-path":
        assert isinstance(raised.value.__cause__, ChromaError)


@pytest.mark.parametrize("call", ["store", "search"])
def test_ac_vec_04_chroma_errors_on_use_are_vector_store_error(chroma, call):
    store("a", ["alpha"], FakeEmbedder())  # the collection now holds 384-d vectors
    wrong_dim = [1.0, 0.0, 0.0]
    if call == "store":
        action = lambda: store("b", ["beta"], lambda texts: [wrong_dim])  # noqa: E731
    else:
        action = lambda: search_similar(wrong_dim)  # noqa: E731
    with pytest.raises(VectorStoreError):
        action()
