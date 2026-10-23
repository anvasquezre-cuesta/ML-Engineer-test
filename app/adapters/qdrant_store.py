"""``VectorStore`` backed by Qdrant: a separate service (docker compose) or embedded.

Same contract as the Chroma adapter, so services and tests do not change:

- IDs: Qdrant point IDs must be integers or UUIDs, so each chunk ID
  ``{doc_id}:{page}:{chunk_index}`` maps to a deterministic UUIDv5; the original
  ID is kept in the payload. Re-ingesting a file rewrites the same points.
- Replace is upsert-then-prune: new points first, then the document's stale
  points are deleted, so a crash never leaves a document with no chunks.
- Cosine distance; Qdrant's score is already a cosine similarity, clamped to [0, 1].
- The collection is created on the first write, sized from the vectors, with a
  keyword index on ``doc_id`` for the prune filter.
- Over the network, transient failures (transport errors, 429/502/503/504) are
  retried with exponential backoff; anything else, or exhausted retries, becomes
  ``UpstreamUnavailable`` (503).
"""

import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from functools import partial
from typing import Any, TypeVar

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.core.config import RAGSettings
from app.domain.errors import UpstreamUnavailable
from app.domain.models import Chunk, RetrievedChunk

T = TypeVar("T")

_POINT_NAMESPACE = uuid.UUID("6f1c2b1e-3a4d-4c55-9e0a-2b7d8c9e1f00")
_TRANSIENT_STATUS = {429, 502, 503, 504}
_WRITE_BATCH = 256
_SCROLL_PAGE = 1024


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, chunk_id))


class QdrantVectorStore:
    def __init__(
        self,
        client: Any,
        collection: str,
        *,
        max_retries: int = 2,
        backoff_s: float = 0.2,
        index_payload: bool = False,
    ) -> None:
        self._client = client
        self._collection = collection
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._index_payload = index_payload

    @classmethod
    def from_settings(cls, settings: RAGSettings) -> "QdrantVectorStore":
        if settings.qdrant_url:
            api_key = (
                settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
            )
            client = QdrantClient(
                url=settings.qdrant_url, api_key=api_key, timeout=int(settings.qdrant_timeout_s)
            )
        else:
            client = QdrantClient(path=settings.qdrant_path)  # embedded, single process
        return cls(
            client,
            settings.collection,
            max_retries=settings.qdrant_max_retries,
            index_payload=settings.qdrant_url is not None,
        )

    def replace_document(
        self, doc_id: str, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> int:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if chunks:
            self._ensure_collection(len(vectors[0]))
        elif not self._exists():
            return 0

        new_ids = [point_id(chunk.chunk_id) for chunk in chunks]
        for start in range(0, len(chunks), _WRITE_BATCH):
            batch = [
                models.PointStruct(id=pid, vector=list(vector), payload=_payload(chunk))
                for pid, chunk, vector in zip(
                    new_ids[start : start + _WRITE_BATCH],
                    chunks[start : start + _WRITE_BATCH],
                    vectors[start : start + _WRITE_BATCH],
                    strict=True,
                )
            ]
            self._call(partial(self._client.upsert, self._collection, batch, wait=True))

        stale = set(self._ids_of(doc_id)) - set(new_ids)
        if stale:
            selector = models.PointIdsList(points=sorted(stale))
            self._call(lambda: self._client.delete(self._collection, selector, wait=True))
        return len(chunks)

    def query(self, vector: Sequence[float], top_k: int) -> list[RetrievedChunk]:
        if not self._exists():
            return []
        response = self._call(
            lambda: self._client.query_points(
                self._collection, query=list(vector), limit=top_k, with_payload=True
            )
        )
        return [
            RetrievedChunk(chunk=_chunk(point.payload), similarity=max(0.0, min(1.0, point.score)))
            for point in response.points
        ]

    def count(self) -> int:
        if not self._exists():
            return 0
        return int(self._call(lambda: self._client.count(self._collection, exact=True)).count)

    def close(self) -> None:
        self._client.close()

    def _exists(self) -> bool:
        return bool(self._call(lambda: self._client.collection_exists(self._collection)))

    def _ensure_collection(self, size: int) -> None:
        if self._exists():
            return
        self._call(
            lambda: self._client.create_collection(
                self._collection,
                vectors_config=models.VectorParams(size=size, distance=models.Distance.COSINE),
            )
        )
        if self._index_payload:  # only a Qdrant server uses payload indexes
            self._call(
                lambda: self._client.create_payload_index(
                    self._collection, "doc_id", field_schema=models.PayloadSchemaType.KEYWORD
                )
            )

    def _ids_of(self, doc_id: str) -> Iterator[str]:
        selector = models.Filter(
            must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
        )
        offset = None
        while True:
            points, offset = self._call(
                partial(
                    self._client.scroll,
                    self._collection,
                    scroll_filter=selector,
                    limit=_SCROLL_PAGE,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
            )
            yield from (str(point.id) for point in points)
            if offset is None:
                return

    def _call(self, operation: Callable[[], T]) -> T:
        for attempt in range(self._max_retries + 1):
            try:
                return operation()
            except (ResponseHandlingException, UnexpectedResponse) as exc:
                transient = (
                    isinstance(exc, ResponseHandlingException)
                    or exc.status_code in _TRANSIENT_STATUS
                )
                if not transient or attempt == self._max_retries:
                    raise UpstreamUnavailable(f"Vector store request failed: {exc}") from exc
                time.sleep(self._backoff_s * 2**attempt)
        raise AssertionError("unreachable")  # pragma: no cover


def _payload(chunk: Chunk) -> dict[str, str | int]:
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "filename": chunk.filename,
        "page": chunk.page,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
    }


def _chunk(payload: dict[str, Any] | None) -> Chunk:
    data = payload or {}
    return Chunk(
        doc_id=str(data["doc_id"]),
        filename=str(data["filename"]),
        page=int(data["page"]),
        chunk_index=int(data["chunk_index"]),
        text=str(data["text"]),
    )
