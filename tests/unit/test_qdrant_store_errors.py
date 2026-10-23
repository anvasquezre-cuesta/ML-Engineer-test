"""Qdrant over the network: transient failures are retried, the rest become 503."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.adapters.qdrant_store import QdrantVectorStore, point_id
from app.container import build_vector_store
from app.core.config import RAGSettings
from app.domain.errors import UpstreamUnavailable


def _status(code: int) -> UnexpectedResponse:
    return UnexpectedResponse(code, "error", b"{}", {})


class FlakyClient:
    """``collection_exists`` and ``count`` fail with the given errors, then succeed."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0

    def _maybe_fail(self) -> None:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)

    def collection_exists(self, name: str) -> bool:
        self._maybe_fail()
        return True

    def count(self, name: str, exact: bool) -> Any:
        return type("Count", (), {"count": 7})()


def _store(client: FlakyClient, retries: int = 2) -> QdrantVectorStore:
    return QdrantVectorStore(client, "docs", max_retries=retries, backoff_s=0)


def test_transport_errors_are_retried_until_success() -> None:
    client = FlakyClient(ResponseHandlingException(ConnectionError("reset")), _status(503))

    assert _store(client).count() == 7
    assert client.calls == 3


def test_exhausted_retries_become_upstream_unavailable() -> None:
    client = FlakyClient(*[ResponseHandlingException(TimeoutError("slow")) for _ in range(3)])

    with pytest.raises(UpstreamUnavailable, match="Vector store request failed"):
        _store(client, retries=2).count()
    assert client.calls == 3  # one try plus two retries


def test_client_errors_are_not_retried() -> None:
    client = FlakyClient(_status(400))

    with pytest.raises(UpstreamUnavailable):
        _store(client).count()
    assert client.calls == 1


def test_server_url_selects_a_remote_client_with_payload_index() -> None:
    # Constructing the client does not connect, so no server is needed here.
    settings = RAGSettings(
        vector_store="qdrant",
        qdrant_url="https://qdrant.internal:6333",
        qdrant_api_key=SecretStr("k"),
    )

    store = QdrantVectorStore.from_settings(settings)

    assert store._index_payload is True
    store.close()


def test_selected_by_config_in_the_composition_root(tmp_path: Path) -> None:
    rag = RAGSettings(vector_store="qdrant", qdrant_path=str(tmp_path / "q"))

    store = build_vector_store(rag)

    assert isinstance(store, QdrantVectorStore)
    store.close()


def test_point_ids_are_deterministic_uuids_per_chunk() -> None:
    assert point_id("abc:0:0") == point_id("abc:0:0")
    assert point_id("abc:0:0") != point_id("abc:0:1")
    assert len(point_id("abc:0:0")) == 36
