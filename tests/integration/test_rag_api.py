"""
Module: tests.integration.test_rag_api
Path: tests/integration/test_rag_api.py
Description: Integration tests for document ingestion and RAG API endpoints.
"""

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.dependencies import get_ingestion_service, get_rag_service
from app.main import app
from app.models.ingestion import IngestionResult


@dataclass
class FakeIngestionService:
    """Provide deterministic ingestion results for API integration tests."""

    def ingest(self, pdf_path: str, source: str) -> IngestionResult:
        return IngestionResult(
            document_id="test-document-id",
            chunks_stored=3,
        )


@dataclass
class FakeRAGService:
    """Provide deterministic RAG responses for API integration tests."""

    def generate_answer(self, question: str) -> dict[str, str | list[str]]:
        return {
            "answer": "The meeting was held on January 22, 2024.",
            "sources": ["meeting_minutes.pdf"],
        }


def test_ingest_endpoint_returns_success_response() -> None:
    app.dependency_overrides[get_ingestion_service] = lambda: FakeIngestionService()

    try:
        client = TestClient(app)

        response = client.post(
            "/api/ingest",
            files={
                "pdf_file": (
                    "document.pdf",
                    b"%PDF-test",
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


def test_ask_endpoint_returns_rag_response() -> None:
    app.dependency_overrides[get_rag_service] = lambda: FakeRAGService()

    try:
        client = TestClient(app)

        response = client.post(
            "/api/ask",
            json={"question": "When was the meeting held?"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "answer": "The meeting was held on January 22, 2024.",
            "sources": ["meeting_minutes.pdf"],
        }
    finally:
        app.dependency_overrides.clear()


def test_ask_endpoint_rejects_empty_question() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/ask",
        json={"question": ""},
    )

    assert response.status_code == 422
