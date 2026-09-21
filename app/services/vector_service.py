"""
Module: app.services.vector_service
Path: app/services/vector_service.py
Description: ChromaDB vector-store adapter for RAG document chunks.
"""

from dataclasses import dataclass
from uuid import uuid4

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import Settings
from app.services.embedding_service import EmbeddingService


class VectorStoreError(RuntimeError):
    """Raised when the vector-store operation cannot be completed."""


@dataclass(frozen=True)
class VectorSearchResult:
    """Represent a retrieved document and its vector distance."""

    document: Document
    distance: float


class VectorStoreService:
    """Store and retrieve document chunks using ChromaDB."""

    def __init__(
        self,
        settings: Settings,
        embedding_service: EmbeddingService,
    ) -> None:
        self._vector_store = Chroma(
            collection_name=settings.chroma_collection_name,
            embedding_function=embedding_service.embedding_function,
            persist_directory=settings.chroma_persist_directory,
        )

    def add_documents(
        self,
        documents: list[Document],
    ) -> list[str]:
        """Add document chunks using unique identifiers."""

        ids = [str(uuid4()) for _ in documents]

        try:
            return self._vector_store.add_documents(
                documents=documents,
                ids=ids,
            )
        except Exception as exc:
            raise VectorStoreError(
                "Failed to store document chunks in the vector store."
            ) from exc

    def similarity_search(
        self,
        query: str,
        k: int,
    ) -> list[VectorSearchResult]:
        """Retrieve the most similar document chunks with their vector distances."""

        try:
            results = self._vector_store.similarity_search_with_score(
                query=query,
                k=k,
            )
        except Exception as exc:
            raise VectorStoreError(
                "Failed to retrieve documents from the vector store."
            ) from exc

        return [
            VectorSearchResult(
                document=document,
                distance=distance,
            )
            for document, distance in results
        ]
