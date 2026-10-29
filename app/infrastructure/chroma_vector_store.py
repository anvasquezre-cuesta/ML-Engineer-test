"""`VectorStore` adapter: embedded Chroma (TRD ADR-008).

Vectors always come from our `Embedder`; the collection has no embedding function, so
Chroma never downloads its default model. Chroma types never cross the port: results
are rebuilt as domain `Chunk`s and every Chroma error becomes `VectorStoreUnavailable`.
"""

from collections.abc import Mapping, Sequence
from typing import cast

import chromadb
from chromadb.api.client import Client
from chromadb.api.collection_configuration import (
    CreateCollectionConfiguration,
    CreateHNSWConfiguration,
)
from chromadb.config import Settings as ChromaSettings
from chromadb.errors import ChromaError

from app.domain.chunking import Chunk
from app.domain.errors import VectorStoreUnavailable

COSINE = CreateCollectionConfiguration(hnsw=CreateHNSWConfiguration(space="cosine"))


class ChromaVectorStore:
    """Chunks with their vectors in a local Chroma collection."""

    def __init__(self, path: str, collection: str) -> None:
        try:
            # Typed as the ClientAPI protocol, which omits close(); the object is a Client.
            self._client = cast(
                Client,
                chromadb.PersistentClient(
                    path=path, settings=ChromaSettings(anonymized_telemetry=False)
                ),
            )
            self._collection = self._client.get_or_create_collection(
                collection, embedding_function=None, configuration=COSINE
            )
        except ChromaError as exc:
            raise VectorStoreUnavailable("Vector store operation failed: open") from exc

    def replace_document(
        self,
        document_id: str,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        try:
            self._collection.delete(where={"document_id": document_id})
            if chunks:
                self._collection.upsert(
                    ids=[chunk.id for chunk in chunks],
                    embeddings=_vectors(embeddings),
                    documents=[chunk.text for chunk in chunks],
                    metadatas=[_metadata(chunk) for chunk in chunks],
                )
        except ChromaError as exc:
            raise VectorStoreUnavailable("Vector store operation failed: write") from exc

    def search(self, embedding: Sequence[float], limit: int) -> list[Chunk]:
        try:
            result = self._collection.query(
                query_embeddings=_vectors([embedding]),
                n_results=limit,
                include=["documents", "metadatas"],
            )
        except ChromaError as exc:
            raise VectorStoreUnavailable("Vector store operation failed: search") from exc
        documents = (result["documents"] or [[]])[0]
        metadatas = (result["metadatas"] or [[]])[0]
        return [_chunk(text, meta) for text, meta in zip(documents, metadatas, strict=True)]

    def all_chunks(self) -> list[Chunk]:
        try:
            result = self._collection.get(include=["documents", "metadatas"])
        except ChromaError as exc:
            raise VectorStoreUnavailable("Vector store operation failed: read") from exc
        documents = result["documents"] or []
        metadatas = result["metadatas"] or []
        return [_chunk(text, meta) for text, meta in zip(documents, metadatas, strict=True)]

    def close(self) -> None:
        """Release Chroma's files (on Windows they stay locked until this runs)."""
        self._client.close()


def _vectors(embeddings: Sequence[Sequence[float]]) -> list[Sequence[float]]:
    return [list(vector) for vector in embeddings]


def _metadata(chunk: Chunk) -> dict[str, str | int]:
    return {
        "document_id": chunk.document_id,
        "file_name": chunk.file_name,
        "page": chunk.page,
        "chunk_index": chunk.chunk_index,
    }


def _chunk(text: str, metadata: Mapping[str, object]) -> Chunk:
    return Chunk(
        document_id=str(metadata["document_id"]),
        file_name=str(metadata["file_name"]),
        page=int(str(metadata["page"])),
        chunk_index=int(str(metadata["chunk_index"])),
        text=text,
    )
