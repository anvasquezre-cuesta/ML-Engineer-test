"""
Module: app.services.embedding_service
Path: app/services/embedding_service.py
Description: Embedding service for document and query embeddings.
"""

from langchain_huggingface import HuggingFaceEmbeddings

from app.config import Settings


class EmbeddingService:
    """Generate document and query embeddings using a reusable model."""

    def __init__(self, settings: Settings) -> None:
        self._embeddings = HuggingFaceEmbeddings(
            model=settings.embedding_model,
        )

    @property
    def embedding_function(self) -> HuggingFaceEmbeddings:
        """Provide the embedding function for vector-store integrations."""

        return self._embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of document texts."""

        return self._embeddings.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""

        return self._embeddings.embed_query(text)
