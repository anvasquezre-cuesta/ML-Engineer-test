"""ChromaDB vector store adapter."""

import chromadb
from app.services.vector_service import VectorStore


class ChromaStore(VectorStore):
    def __init__(self, persist_dir: str, collection_name: str):
        # ponytail: single global collection — chunks are doc_id-scoped in metadata; per-doc collections only if retrieval quality demands it
        self.client = chromadb.PersistentClient(persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def add_chunks(self, ids: list[str], embeddings: list[list[float]],
                   documents: list[str], metadatas: list[dict]) -> None:
        # ponytail: upsert for deterministic AD-5 idempotency; collection.add silently ignores dup IDs in chroma 1.5.9
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )

    def query(self, query_embedding: list[float], top_k: int) -> list[dict]:
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )
        out = []
        for i, doc in enumerate(results["documents"][0]):
            out.append({
                "id": results["ids"][0][i],
                "text": doc,
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i]
            })
        return out
