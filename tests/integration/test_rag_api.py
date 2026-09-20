"""
Module: tests.integration.test_rag_api
Path: tests/integration/test_rag_api.py
Description: Integration tests for document ingestion and RAG API endpoints.
"""

from dataclasses import dataclass

import pymupdf
from fastapi.testclient import TestClient

from app.dependencies import get_ingestion_service, get_rag_service
from app.main import app
from app.models.ingestion import IngestionResult
from app.services.llm_provider import LLMProviderError
from app.services.vector_service import VectorStoreError


@dataclass
class FakeIngestionService:
    """Provide deterministic ingestion output for API integration tests."""

    def ingest(self, pdf_path: str, source: str) -> IngestionResult:
        return IngestionResult(
            document_id="test-document-id",
            chunks_stored=3,
        )


@dataclass
class FakeRAGService:
    """Provide deterministic RAG output for API integration tests."""

    def generate_answer(self, question: str) -> dict[str, str | list[str]]:
        return {
            "answer": "The answer is in the test document.",
            "sources": ["test.pdf"],
        }


@dataclass
class FailingRAGService:
    """Simulate an infrastructure failure during RAG retrieval."""

    def generate_answer(self, question: str) -> dict[str, str | list[str]]:
        raise VectorStoreError("Simulated vector store failure.")


@dataclass
class FailingLLMRAGService:
    """Simulate an LLM provider failure during RAG generation."""

    def generate_answer(self, question: str) -> dict[str, str | list[str]]:
        raise LLMProviderError("Simulated LLM provider failure.")


def create_valid_pdf() -> bytes:
    """Create a minimal valid one-page PDF for API testing."""
    document = pymupdf.open()
    document.new_page()

    try:
        return document.tobytes()
    finally:
        document.close()


def test_ingest_endpoint_returns_success() -> None:
    app.dependency_overrides[get_ingestion_service] = lambda: FakeIngestionService()

    try:
        client = TestClient(app)

        response = client.post(
            "/api/ingest",
            files={
                "pdf_file": (
                    "document.pdf",
                    create_valid_pdf(),
                    "application/pdf",
                )
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "chunks_stored": 3,
        }
    finally:
        app.dependency_overrides.clear()


def test_ask_endpoint_returns_answer_and_sources() -> None:
    app.dependency_overrides[get_rag_service] = lambda: FakeRAGService()

    try:
        client = TestClient(app)

        response = client.post(
            "/api/ask",
            json={"question": "What does the document say?"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "answer": "The answer is in the test document.",
            "sources": ["test.pdf"],
        }
    finally:
        app.dependency_overrides.clear()


def test_vector_store_failure_returns_service_unavailable() -> None:
    app.dependency_overrides[get_rag_service] = lambda: FailingRAGService()

    try:
        client = TestClient(app)

        response = client.post(
            "/api/ask",
            json={"question": "What does the document say?"},
        )

        assert response.status_code == 503
        assert response.json() == {
            "detail": "The document retrieval service is temporarily unavailable."
        }
    finally:
        app.dependency_overrides.clear()


def test_llm_provider_failure_returns_bad_gateway() -> None:
    app.dependency_overrides[get_rag_service] = lambda: FailingLLMRAGService()

    try:
        client = TestClient(app)

        response = client.post(
            "/api/ask",
            json={"question": "What does the document say?"},
        )

        assert response.status_code == 502
        assert response.json() == {
            "detail": "The language model service is temporarily unavailable."
        }
    finally:
        app.dependency_overrides.clear()
