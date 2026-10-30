import pytest

from app.config import get_settings
from app.services import embedding_service
from app.services.vector_service import _collection


def model_loaded_in_unit_test(*args):
    raise AssertionError("model loaded in a unit test")


@pytest.fixture
def chroma(tmp_path, monkeypatch):
    """Chroma in tmp_path with the fake model name; caches cleared around the test."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("EMBEDDING_MODEL", "fake-384")
    monkeypatch.setattr(embedding_service, "_load_model", model_loaded_in_unit_test)
    get_settings.cache_clear()
    _collection.cache_clear()
    yield
    get_settings.cache_clear()
    _collection.cache_clear()
