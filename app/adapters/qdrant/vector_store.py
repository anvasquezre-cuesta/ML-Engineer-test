"""VectorStore backed by Qdrant."""

from collections.abc import Sequence

import qdrant_client
from qdrant_client import models

from app import config
from app.adapters.qdrant import retry
from app.domain import ids
from app.domain import rag
from app.ports import vector_store

DOCUMENT_KEY = "document_key"


def _document_filter(document_key: str) -> models.Filter:
    """Builds the filter selecting one document's points.

    Args:
        document_key: Identity of the document.

    Returns:
        The Qdrant filter.
    """
    return models.Filter(
        must=[
            models.FieldCondition(
                key=DOCUMENT_KEY, match=models.MatchValue(value=document_key)
            )
        ]
    )


def _chunk(payload: dict[str, object]) -> rag.Chunk:
    """Rebuilds a chunk from a point's payload.

    Args:
        payload: The stored payload.

    Returns:
        The chunk.
    """
    return rag.Chunk(
        document_key=str(payload["document_key"]),
        content_hash=str(payload["content_hash"]),
        page_number=int(str(payload["page_number"])),
        chunk_index=int(str(payload["chunk_index"])),
        start_char=int(str(payload["start_char"])),
        end_char=int(str(payload["end_char"])),
        text=str(payload["text"]),
        strategy=str(payload["strategy"]),
    )


class QdrantVectorStore(vector_store.VectorStore):
    """Stores chunks as points keyed by deterministic ids, one collection."""

    def __init__(
        self,
        client: qdrant_client.AsyncQdrantClient,
        settings: config.QdrantSettings,
        collection: str,
        dimension: int,
    ) -> None:
        """Initializes the store.

        Args:
            client: An open Qdrant client.
            settings: Timeouts and retry budget.
            collection: Collection name, specific to the embedding model.
            dimension: Length of the stored vectors.
        """
        self._client = client
        self._settings = settings
        self._collection = collection
        self._dimension = dimension
        self._ready = False

    async def ensure_collection(self) -> None:
        """Creates the collection and payload indexes if they are missing.

        Every other method calls it first, so the collection appears on
        first use and startup never needs Qdrant.
        """
        if self._ready:
            return

        async def create() -> None:
            if await self._client.collection_exists(self._collection):
                return
            await self._client.create_collection(
                self._collection,
                vectors_config=models.VectorParams(
                    size=self._dimension, distance=models.Distance.COSINE
                ),
                timeout=self._settings.timeout_s,
            )
            await self._client.create_payload_index(
                self._collection,
                DOCUMENT_KEY,
                models.PayloadSchemaType.KEYWORD,
                wait=True,
            )

        await retry.call_with_retries(
            create, self._settings, action="ensure_collection"
        )
        self._ready = True

    async def upsert(self, chunks: Sequence[rag.EmbeddedChunk]) -> None:
        """Stores chunks; writing the same chunk twice leaves one copy.

        Args:
            chunks: The chunks and their vectors.
        """
        await self.ensure_collection()
        points = [
            models.PointStruct(
                id=ids.chunk_point_id(item.chunk),
                vector=list(item.vector),
                payload={
                    "document_key": item.chunk.document_key,
                    "content_hash": item.chunk.content_hash,
                    "page_number": item.chunk.page_number,
                    "chunk_index": item.chunk.chunk_index,
                    "start_char": item.chunk.start_char,
                    "end_char": item.chunk.end_char,
                    "text": item.chunk.text,
                    "strategy": item.chunk.strategy,
                },
            )
            for item in chunks
        ]
        if not points:
            return
        await retry.call_with_retries(
            lambda: self._client.upsert(
                self._collection,
                points,
                wait=True,
                timeout=self._settings.timeout_s,
            ),
            self._settings,
            action="upsert",
        )

    async def get_document(
        self, document_key: str
    ) -> rag.DocumentRecord | None:
        """Reads what is stored for one document.

        Args:
            document_key: Identity of the document.

        Returns:
            The document record, or ``None`` if nothing is stored for it.
        """
        await self.ensure_collection()
        selector = _document_filter(document_key)
        counted = await retry.call_with_retries(
            lambda: self._client.count(
                self._collection, count_filter=selector, exact=True
            ),
            self._settings,
            action="count",
        )
        if counted.count == 0:
            return None
        points, _ = await retry.call_with_retries(
            lambda: self._client.scroll(
                self._collection,
                scroll_filter=selector,
                limit=1,
                with_payload=True,
                timeout=self._settings.timeout_s,
            ),
            self._settings,
            action="scroll",
        )
        payload = points[0].payload or {}
        return rag.DocumentRecord(
            document_key=document_key,
            content_hash=str(payload["content_hash"]),
            chunk_count=counted.count,
        )

    async def list_documents(self) -> list[rag.DocumentRecord]:
        """Lists every stored document.

        Returns:
            One record per document, ordered by key.
        """
        await self.ensure_collection()
        facets = await retry.call_with_retries(
            lambda: self._client.facet(
                self._collection,
                key=DOCUMENT_KEY,
                limit=10_000,
                exact=True,
                timeout=self._settings.timeout_s,
            ),
            self._settings,
            action="facet",
        )
        records = []
        for hit in sorted(facets.hits, key=lambda hit: str(hit.value)):
            record = await self.get_document(str(hit.value))
            if record is not None:
                records.append(record)
        return records

    async def delete_document(self, document_key: str) -> int:
        """Deletes every chunk of one document.

        Args:
            document_key: Identity of the document.

        Returns:
            The number of chunks deleted.
        """
        await self.ensure_collection()
        record = await self.get_document(document_key)
        if record is None:
            return 0
        await retry.call_with_retries(
            lambda: self._client.delete(
                self._collection,
                points_selector=models.FilterSelector(
                    filter=_document_filter(document_key)
                ),
                wait=True,
                timeout=self._settings.timeout_s,
            ),
            self._settings,
            action="delete",
        )
        return record.chunk_count

    async def search(
        self, vector: rag.Vector, top_k: int
    ) -> list[rag.ScoredChunk]:
        """Finds the chunks closest to ``vector``.

        Args:
            vector: The query vector.
            top_k: Maximum number of chunks to return.

        Returns:
            The closest chunks, best first.
        """
        await self.ensure_collection()
        response = await retry.call_with_retries(
            lambda: self._client.query_points(
                self._collection,
                query=list(vector),
                limit=top_k,
                with_payload=True,
                timeout=self._settings.timeout_s,
            ),
            self._settings,
            action="query",
        )
        return [
            rag.ScoredChunk(
                chunk=_chunk(point.payload or {}), score=point.score
            )
            for point in response.points
        ]

    async def hybrid_search(  # noqa: DOC501, DOC503
        self, query: rag.SearchQuery, top_k: int
    ) -> list[rag.ScoredChunk]:
        """Finds the best chunks by fusing dense and keyword rankings.

        Keyword statistics count only the chunks currently stored, so the
        ranking does not depend on what was replaced or deleted before.

        Args:
            query: The question's dense and sparse embeddings.
            top_k: Maximum number of chunks to return.

        Returns:
            The best chunks, best first.
        """
        raise NotImplementedError
