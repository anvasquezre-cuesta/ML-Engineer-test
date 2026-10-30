"""Vector store: embedded Chroma, cosine, chunk ids `doc_id:page:chunk`."""

from functools import lru_cache
from typing import Protocol

import chromadb
from chromadb.config import Settings
from chromadb.errors import ChromaError

from app.config import get_settings
from app.services.embedding_service import Embedder, get_embeddings


class VectorStoreError(RuntimeError):
    """The vector store is unusable (bad path, other model, Chroma failure)."""


@lru_cache
def _collection():
    """Open the cosine collection once; refuse one built with another model."""
    settings = get_settings()
    try:
        client = chromadb.PersistentClient(
            path=settings.chroma_path, settings=Settings(anonymized_telemetry=False)
        )
        collection = client.get_or_create_collection(
            settings.chroma_collection,
            configuration={"hnsw": {"space": "cosine"}},
            metadata={"embedding_model": settings.embedding_model},
            embedding_function=None,
        )
    except ChromaError as err:
        raise VectorStoreError(f"cannot open the vector store: {err}") from err
    stored_model = (collection.metadata or {}).get("embedding_model")
    if stored_model != settings.embedding_model:
        raise VectorStoreError(
            f"collection built with {stored_model!r}, not {settings.embedding_model!r}"
        )
    return collection


def init_collection() -> None:
    """Create the collection if it does not exist."""
    _collection()


class ChunkStore(Protocol):
    def __call__(
        self, chunks: list[str], metadata: list[dict], embed: Embedder
    ) -> None: ...


class ChunkSearch(Protocol):
    def __call__(self, query_embedding: list[float], top_k: int) -> list[dict]: ...


def store_document_chunks(
    chunks: list[str],
    metadata: list[dict],
    embed: Embedder = get_embeddings,
) -> None:
    """Embed and store chunks, replacing any earlier chunks of the same documents."""
    if not chunks:
        return
    embeddings = embed(chunks)
    ids = [f"{m['doc_id']}:{m['page']}:{m['chunk']}" for m in metadata]
    doc_ids = sorted({m["doc_id"] for m in metadata})
    collection = _collection()
    try:
        collection.delete(where={"doc_id": {"$in": doc_ids}})
        collection.add(
            ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadata
        )
    except ChromaError as err:
        raise VectorStoreError(f"cannot store the chunks: {err}") from err


def search_similar(query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """Return the most similar chunks: text, cosine score and origin."""
    try:
        found = _collection().query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
    except ChromaError as err:
        raise VectorStoreError(f"cannot search the chunks: {err}") from err
    return [
        {
            "text": text,
            "score": 1 - distance,
            **{k: meta[k] for k in ("filename", "page", "chunk")},
        }
        for text, meta, distance in zip(
            found["documents"][0],
            found["metadatas"][0],
            found["distances"][0],
            strict=True,
        )
    ]
