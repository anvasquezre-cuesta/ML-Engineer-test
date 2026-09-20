"""
Module: tests.e2e.test_document_intelligence_e2e
Path: tests/e2e/test_document_intelligence_e2e.py
Description: End-to-end test for the document ingestion and RAG workflow.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.e2e
def test_document_ingestion_and_rag_end_to_end() -> None:
    """Verify the complete ingestion-to-question-answering workflow."""
    pdf_path = Path("sample_pdfs/meeting_minutes.pdf")

    with TestClient(app) as client:
        with pdf_path.open("rb") as pdf_file:
            ingest_response = client.post(
                "/api/ingest",
                files={
                    "pdf_file": (
                        pdf_path.name,
                        pdf_file,
                        "application/pdf",
                    )
                },
            )

        assert ingest_response.status_code == 200

        ingest_data = ingest_response.json()
        assert ingest_data["status"] == "ok"
        assert ingest_data["chunks_stored"] > 0

        ask_response = client.post(
            "/api/ask",
            json={
                "question": (
                    "When is the full migration to AWS expected to be completed?"
                )
            },
        )

        assert ask_response.status_code == 200

        rag_data = ask_response.json()
        assert "Q3 2024" in rag_data["answer"]
        assert pdf_path.name in rag_data["sources"]
