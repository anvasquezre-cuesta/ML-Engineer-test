"""Chroma failures surface as ``UpstreamUnavailable`` (503), never as raw library errors."""

from typing import Any, NoReturn

import pytest
from chromadb.errors import InternalError

from app.adapters.chroma_store import ChromaVectorStore
from app.domain.errors import UpstreamUnavailable
from app.domain.models import Chunk


def _fail(*args: Any, **kwargs: Any) -> NoReturn:
    raise InternalError("disk I/O error")


class BrokenCollection:
    get = upsert = delete = query = count = staticmethod(_fail)


class StubClient:
    def __init__(self, collection: object) -> None:
        self.collection = collection

    def get_or_create_collection(self, name: str, metadata: dict[str, str]) -> object:
        return self.collection

    def get_max_batch_size(self) -> int:
        return 100


def _broken_store() -> ChromaVectorStore:
    return ChromaVectorStore(StubClient(BrokenCollection()), "docs")


def test_unreachable_store_at_startup() -> None:
    class DownClient(StubClient):
        get_or_create_collection = staticmethod(_fail)  # type: ignore[assignment]

    with pytest.raises(UpstreamUnavailable, match="unavailable"):
        ChromaVectorStore(DownClient(None), "docs")


def test_write_failure() -> None:
    chunk = Chunk("doc", "a.pdf", 0, 0, "text")

    with pytest.raises(UpstreamUnavailable, match="write failed"):
        _broken_store().replace_document("doc", [chunk], [[1.0]])


def test_query_failure() -> None:
    with pytest.raises(UpstreamUnavailable, match="query failed"):
        _broken_store().query([1.0], top_k=3)


def test_count_failure() -> None:
    with pytest.raises(UpstreamUnavailable):
        _broken_store().count()
