"""``VectorStore`` backed by an embedded Chroma collection.

IDs are ``{doc_id}:{page}:{chunk_index}`` with ``doc_id`` the SHA-256 of the
file, so different files never collide and re-ingesting a file is idempotent.

Replacing a document is upsert-then-prune rather than delete-then-add: the new
chunks are written first and only IDs that no longer exist are removed, so a
crash midway never leaves the document with no chunks at all.

The collection uses cosine space explicitly (Chroma's default is L2, which
would make a similarity threshold meaningless). Chroma failures surface as
``UpstreamUnavailable``.
"""

from collections.abc import Iterator, Sequence
from typing import Any

import chromadb
from chromadb.errors import ChromaError

from app.core.config import RAGSettings
from app.domain.errors import UpstreamUnavailable
from app.domain.models import Chunk, RetrievedChunk


class ChromaVectorStore:
    def __init__(self, client: Any, collection_name: str) -> None:
        self._client = client
        try:
            self._collection = client.get_or_create_collection(
                collection_name, metadata={"hnsw:space": "cosine"}
            )
            self._max_batch = int(client.get_max_batch_size())
        except ChromaError as exc:
            raise UpstreamUnavailable(f"Vector store unavailable: {exc}") from exc

    @classmethod
    def persistent(cls, settings: RAGSettings) -> "ChromaVectorStore":
        return cls(chromadb.PersistentClient(path=settings.chroma_path), settings.collection)

    def replace_document(
        self, doc_id: str, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> int:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        new_ids = [chunk.chunk_id for chunk in chunks]
        try:
            stale = set(self._collection.get(where={"doc_id": doc_id}, include=[])["ids"])
            for start, end in self._batches(len(chunks)):
                self._collection.upsert(
                    ids=new_ids[start:end],
                    embeddings=[list(v) for v in vectors[start:end]],
                    documents=[c.text for c in chunks[start:end]],
                    metadatas=[_metadata(c) for c in chunks[start:end]],
                )
            stale -= set(new_ids)
            if stale:
                self._collection.delete(ids=sorted(stale))
        except ChromaError as exc:
            raise UpstreamUnavailable(f"Vector store write failed: {exc}") from exc
        return len(chunks)

    def query(self, vector: Sequence[float], top_k: int) -> list[RetrievedChunk]:
        try:
            result = self._collection.query(
                query_embeddings=[list(vector)],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
        except ChromaError as exc:
            raise UpstreamUnavailable(f"Vector store query failed: {exc}") from exc
        return [
            RetrievedChunk(chunk=_chunk(text, meta), similarity=_similarity(distance))
            for text, meta, distance in zip(
                result["documents"][0], result["metadatas"][0], result["distances"][0], strict=True
            )
        ]

    def count(self) -> int:
        try:
            return int(self._collection.count())
        except ChromaError as exc:
            raise UpstreamUnavailable(f"Vector store unavailable: {exc}") from exc

    def _batches(self, total: int) -> Iterator[tuple[int, int]]:
        for start in range(0, total, self._max_batch):
            yield start, min(start + self._max_batch, total)


def _metadata(chunk: Chunk) -> dict[str, str | int]:
    return {
        "doc_id": chunk.doc_id,
        "filename": chunk.filename,
        "page": chunk.page,
        "chunk_index": chunk.chunk_index,
    }


def _chunk(text: str, meta: dict[str, Any]) -> Chunk:
    return Chunk(
        doc_id=str(meta["doc_id"]),
        filename=str(meta["filename"]),
        page=int(meta["page"]),
        chunk_index=int(meta["chunk_index"]),
        text=text,
    )


def _similarity(cosine_distance: float) -> float:
    """Cosine distance is 0..2; opposite vectors (negative cosine) count as unrelated."""
    return max(0.0, min(1.0, 1.0 - cosine_distance))
