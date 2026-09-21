"""
Module: tests.unit.test_vector_service
Path: tests/unit/test_vector_service.py
Description: Unit tests for the ChromaDB vector-store adapter.
"""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.config import Settings
from app.services.embedding_service import EmbeddingService
from app.services.vector_service import VectorStoreError, VectorStoreService


def create_vector_store_service() -> tuple[VectorStoreService, MagicMock]:
    settings = Settings(
        chroma_persist_directory="./test-data/chroma",
        chroma_collection_name="test-documents",
    )
    embedding_service = MagicMock(spec=EmbeddingService)
    mock_chroma = MagicMock()

    with patch("app.services.vector_service.Chroma", return_value=mock_chroma):
        service = VectorStoreService(
            settings=settings,
            embedding_service=embedding_service,
        )

    return service, mock_chroma


def test_add_documents_returns_unique_ids() -> None:
    service, vector_store = create_vector_store_service()
    vector_store.add_documents.return_value = ["id-1", "id-2"]

    documents = [
        Document(page_content="First document"),
        Document(page_content="Second document"),
    ]

    result = service.add_documents(documents)

    assert result == ["id-1", "id-2"]

    ids = vector_store.add_documents.call_args.kwargs["ids"]
    assert len(ids) == 2
    assert len(set(ids)) == 2


def test_add_documents_translates_vector_store_failure() -> None:
    service, vector_store = create_vector_store_service()
    vector_store.add_documents.side_effect = RuntimeError("Chroma unavailable")

    with pytest.raises(VectorStoreError, match="Failed to store document chunks"):
        service.add_documents([Document(page_content="Test document")])


def test_similarity_search_returns_documents_and_distances() -> None:
    service, vector_store = create_vector_store_service()

    document = Document(
        page_content="Retrieved content",
        metadata={"source": "document.pdf"},
    )
    vector_store.similarity_search_with_score.return_value = [(document, 0.25)]

    results = service.similarity_search(query="What is this about?", k=1)

    assert len(results) == 1
    assert results[0].document.page_content == "Retrieved content"
    assert results[0].document.metadata["source"] == "document.pdf"
    assert results[0].distance == 0.25

    vector_store.similarity_search_with_score.assert_called_once_with(
        query="What is this about?",
        k=1,
    )


def test_similarity_search_translates_vector_store_failure() -> None:
    service, vector_store = create_vector_store_service()
    vector_store.similarity_search_with_score.side_effect = RuntimeError(
        "Chroma unavailable"
    )

    with pytest.raises(VectorStoreError, match="Failed to retrieve documents"):
        service.similarity_search(query="Test question", k=3)
