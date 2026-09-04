import chromadb
from chromadb.errors import InvalidArgumentError
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_fixed

from app.core.errors import VectorStoreError
from app.models.domain import RetrievedChunk

# Embedded Chroma has no network to time out on, but its sqlite file can be briefly locked
# by a concurrent write. Bad input is not worth retrying.
transient = retry(
    retry=retry_if_not_exception_type((InvalidArgumentError, ValueError)),
    stop=stop_after_attempt(3),
    wait=wait_fixed(0.2),
    reraise=True,
)


class ChromaStore:
    """Embedded Chroma persisted to a directory. Embeddings are supplied by us, so Chroma
    never downloads its own default model."""

    def __init__(self, path: str, collection: str):
        try:
            self.client = chromadb.PersistentClient(path=path)
            self.collection = self.client.get_or_create_collection(
                collection, metadata={"hnsw:space": "cosine"}
            )
        except Exception as exc:
            raise VectorStoreError(f"could not open vector store at {path}: {exc}") from exc

    @transient
    def add(self, ids, texts, embeddings, sources) -> None:
        try:
            self.collection.add(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=[{"source": s} for s in sources],
            )
        except Exception as exc:
            raise VectorStoreError(f"vector store write failed: {exc}") from exc

    @transient
    def query(self, embedding, top_k) -> list[RetrievedChunk]:
        try:
            if self.collection.count() == 0:
                return []
            res = self.collection.query(
                query_embeddings=[embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise VectorStoreError(f"vector store query failed: {exc}") from exc
        return [
            RetrievedChunk(text=doc, source=meta["source"], score=1 - dist)
            for doc, meta, dist in zip(
                res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True
            )
        ]
