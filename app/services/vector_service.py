"""Vector store protocol for RAG."""

from typing import Protocol


class VectorStore(Protocol):
    def add_chunks(self, ids: list[str], embeddings: list[list[float]],
                   documents: list[str], metadatas: list[dict]) -> None: ...
    def query(self, query_embedding: list[float], top_k: int) -> list[dict]: ...
