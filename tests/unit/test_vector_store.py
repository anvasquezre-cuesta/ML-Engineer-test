import pytest

from app.services.vector_service import ChromaStore


@pytest.fixture
def store(tmp_path):
    return ChromaStore(str(tmp_path / "chroma"), "docs")


def test_two_ingests_with_distinct_ids_both_persist(store):
    store.add(["a:0", "a:1"], ["alpha", "beta"], [[1, 0], [0, 1]], ["f#0", "f#1"])
    store.add(["b:0", "b:1"], ["alpha", "beta"], [[1, 0], [0, 1]], ["g#0", "g#1"])
    assert store.collection.count() == 4


def test_query_returns_nearest_with_its_source(store):
    store.add(["a:0", "a:1"], ["alpha", "beta"], [[1, 0], [0, 1]], ["f#0", "f#1"])
    [hit] = store.query([0.9, 0.1], top_k=1)
    assert (hit.text, hit.source) == ("alpha", "f#0")
    assert hit.score > 0.9


def test_top_k_larger_than_store_is_fine(store):
    store.add(["a:0"], ["alpha"], [[1, 0]], ["f#0"])
    assert len(store.query([1, 0], top_k=5)) == 1


def test_empty_store_returns_nothing(store):
    assert store.query([1, 0], top_k=5) == []


def test_reused_id_is_silently_dropped_by_chroma(store):
    """Chroma neither errors nor overwrites on a repeated id. This is why ingest mints a
    fresh id per upload: reusing ids would make a second ingest vanish without a trace."""
    store.add(["a:0"], ["alpha"], [[1, 0]], ["f#0"])
    store.add(["a:0"], ["beta"], [[0, 1]], ["g#0"])
    assert store.collection.count() == 1
    [hit] = store.query([1, 0], top_k=1)
    assert (hit.text, hit.source) == ("alpha", "f#0")
