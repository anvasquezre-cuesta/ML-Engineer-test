"""Qdrant adapter with explicit model/ledger ownership on the supported server.

Qdrant 1.13 does not persist collection metadata. A reserved, non-retrievable
manifest point establishes ownership; real fragments always have kind='chunk'.
All cooperating writers/cleanup commands must share the same local ledger lock.
This is not a defense against an administrator or an unrelated Qdrant writer.
"""

import asyncio
import hashlib
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.core.config import Settings
from app.core.embedding_model import MODEL_DIMENSIONS, MODEL_NAME, MODEL_REVISION


MANIFEST_ID = str(uuid5(NAMESPACE_URL, "document-intelligence/collection-manifest/v1"))


class VectorStoreError(RuntimeError):
    pass


class VectorCompatibilityError(VectorStoreError):
    pass


class VectorTimeoutError(VectorStoreError):
    """The vector store did not respond within its configured deadline."""


class VectorUnavailableError(VectorStoreError):
    """The vector store could not be reached or returned a transient error."""


class VectorRequestError(VectorStoreError):
    """The vector store rejected a request or returned an invalid response."""


def endpoint_key(url: str) -> str:
    return hashlib.sha256(url.rstrip("/").encode()).hexdigest()


def chunk_id(ingestion_id: str, index: int) -> str:
    return str(uuid5(UUID(ingestion_id), f"chunk:{index}"))


class IngestionVectorStore:
    def __init__(self, settings: Settings, ledger_id: str):
        self.settings = settings
        self.collection = settings.ingest_collection
        self.ledger_id = ledger_id
        self.endpoint = endpoint_key(settings.qdrant_url)
        self.lock_name = "collection-" + hashlib.sha256((self.endpoint + self.collection).encode()).hexdigest()
        self.client = AsyncQdrantClient(
            url=settings.qdrant_url, timeout=settings.qdrant_timeout_seconds, check_compatibility=False,
        )
        self.manifest = {
            "kind": "collection_manifest", "schema_version": 1, "ledger_id": ledger_id,
            "model_name": MODEL_NAME, "model_revision": MODEL_REVISION,
            "dimensions": MODEL_DIMENSIONS, "endpoint_key": self.endpoint,
        }

    async def _call(self, function, *, read=False, **kwargs):
        for attempt in range(self.settings.qdrant_read_retries + 1 if read else 1):
            try:
                return await function(**kwargs)
            except UnexpectedResponse as error:
                transient = error.status_code in {408, 429, 500, 502, 503, 504}
                failure = VectorUnavailableError if transient else VectorRequestError
            except ResponseHandlingException as error:
                # The HTTP client wraps transport exceptions. Never inspect or
                # expose its message, which can contain URLs or response data.
                source = error.source
                if isinstance(source, (httpx.TimeoutException, TimeoutError)):
                    transient, failure = True, VectorTimeoutError
                elif isinstance(source, httpx.TransportError):
                    transient, failure = True, VectorUnavailableError
                else:
                    transient, failure = False, VectorRequestError
            except (httpx.TimeoutException, TimeoutError):
                transient, failure = True, VectorTimeoutError
            except httpx.TransportError:
                transient, failure = True, VectorUnavailableError
            # Unexpected programming errors are not dependency failures and
            # must not be retried or silently reported as a Qdrant outage.
            if read and transient and attempt < self.settings.qdrant_read_retries:
                await asyncio.sleep(0.1 * 2 ** attempt)
                continue
            raise failure("Vector store operation failed; mutation outcome may be unknown") from None

    def _condition(self, key, value):
        return models.FieldCondition(key=key, match=models.MatchValue(value=value))

    def attempt_filter(self, record):
        return models.Filter(must=[
            self._condition("kind", "chunk"), self._condition("schema_version", 1),
            self._condition("ledger_id", self.ledger_id), self._condition("ingestion_id", record.ingestion_id),
            self._condition("document_id", record.document_id), self._condition("model_revision", MODEL_REVISION),
            self._condition("model_name", MODEL_NAME),
        ])

    async def ensure(self, *, create: bool):
        """Caller holds collection lock. Never adopt an existing unmarked collection."""
        exists = await self._call(self.client.collection_exists, read=True, collection_name=self.collection)
        if not exists:
            if not create:
                raise VectorCompatibilityError("The recorded collection is missing")
            await self._call(
                self.client.create_collection, collection_name=self.collection,
                vectors_config=models.VectorParams(size=MODEL_DIMENSIONS, distance=models.Distance.COSINE),
                timeout=self.settings.qdrant_timeout_seconds,
            )
            # Only the successful creator may write the manifest. An interrupted
            # creation is refused on the next run rather than silently adopted.
            await self._call(
                self.client.upsert, collection_name=self.collection,
                points=[models.PointStruct(id=MANIFEST_ID, vector=[1.0] + [0.0] * 383, payload=self.manifest)],
                wait=True, ordering=models.WriteOrdering.STRONG, timeout=self.settings.qdrant_timeout_seconds,
            )
        info = await self._call(self.client.get_collection, read=True, collection_name=self.collection)
        vectors = info.config.params.vectors
        if not isinstance(vectors, models.VectorParams) or vectors.size != MODEL_DIMENSIONS or vectors.distance != models.Distance.COSINE:
            raise VectorCompatibilityError("Collection vector configuration is incompatible")
        manifest = await self._call(
            self.client.retrieve, read=True, collection_name=self.collection,
            ids=[MANIFEST_ID], with_payload=True, with_vectors=False,
        )
        if len(manifest) != 1 or manifest[0].payload != self.manifest:
            raise VectorCompatibilityError("Collection belongs to another model or ledger, or has no manifest")
        valid_chunks = models.Filter(must=[
            self._condition("kind", "chunk"), self._condition("schema_version", 1),
            self._condition("ledger_id", self.ledger_id), self._condition("model_name", MODEL_NAME),
            self._condition("model_revision", MODEL_REVISION),
        ])
        valid_manifest = models.HasIdCondition(has_id=[MANIFEST_ID])
        bad = await self._call(
            self.client.count, read=True, collection_name=self.collection, exact=True,
            count_filter=models.Filter(must_not=[models.Filter(should=[valid_manifest, valid_chunks])]),
        )
        if bad.count:
            raise VectorCompatibilityError("Collection contains incompatible or untagged points")

    async def upsert(self, points):
        result = await self._call(
            self.client.upsert, collection_name=self.collection, points=points, wait=True,
            ordering=models.WriteOrdering.STRONG, timeout=self.settings.qdrant_timeout_seconds,
        )
        if result.status != models.UpdateStatus.COMPLETED:
            raise VectorStoreError("Qdrant did not confirm the complete write")

    async def count(self, record):
        result = await self._call(
            self.client.count, read=True, collection_name=self.collection,
            count_filter=self.attempt_filter(record), exact=True,
        )
        return result.count

    async def verify(self, record):
        if await self.count(record) != record.expected_chunks:
            raise VectorStoreError("Stored fragment count does not match the ingestion")
        for start in range(0, record.expected_chunks, self.settings.qdrant_batch_size):
            ids = [chunk_id(record.ingestion_id, i) for i in range(start, min(record.expected_chunks, start + self.settings.qdrant_batch_size))]
            points = await self._call(
                self.client.retrieve, read=True, collection_name=self.collection, ids=ids,
                with_payload=True, with_vectors=False,
            )
            if {str(point.id) for point in points} != set(ids) or any(
                point.payload.get("ingestion_id") != record.ingestion_id
                or point.payload.get("document_id") != record.document_id
                or point.payload.get("ledger_id") != self.ledger_id
                or not point.payload.get("text", "").strip() for point in points
            ):
                raise VectorStoreError("Stored fragment identities are incomplete")

    async def clear_points(self, record):
        """Delete only the exact ledger/document/ingestion/model filter, never all."""
        result = await self._call(
            self.client.delete, collection_name=self.collection,
            points_selector=models.FilterSelector(filter=self.attempt_filter(record)),
            wait=True, ordering=models.WriteOrdering.STRONG, timeout=self.settings.qdrant_timeout_seconds,
        )
        if result.status != models.UpdateStatus.COMPLETED or await self.count(record):
            raise VectorStoreError("Scoped cleanup has not been confirmed")

    async def aclose(self):
        await self.client.close()
