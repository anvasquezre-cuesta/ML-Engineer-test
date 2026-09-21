"""
Module: tests.integration.test_api
Path: tests/integration/test_api.py
Description: Integration tests for the document extraction and health endpoints.
"""

from dataclasses import dataclass

import pymupdf
from fastapi.testclient import TestClient

from app.dependencies import get_extraction_service, get_ocr_service
from app.main import app
from app.models.extraction import ExtractedNameResult, ExtractionResult
from app.models.ocr import OCRDocument


def create_valid_pdf() -> bytes:
    """Create a minimal valid one-page PDF for API integration tests."""
    document = pymupdf.open()
    document.new_page()

    try:
        return document.tobytes()
    finally:
        document.close()


@dataclass
class FakeOCRService:
    """Provide deterministic OCR output for API integration tests."""

    def extract(self, pdf_path: str) -> OCRDocument:
        return OCRDocument(pages=[])


@dataclass
class FakeExtractionService:
    """Provide deterministic extraction output for API integration tests."""

    def extract(
        self,
        document: OCRDocument,
        candidate_names: list[str],
    ) -> ExtractionResult:
        return ExtractionResult(
            extracted_names=[
                ExtractedNameResult(
                    name="John Smith",
                    page_number=0,
                    x=72.0,
                    y=100.0,
                    width=80.0,
                    height=15.0,
                )
            ],
            fuzzy_matches=[],
        )


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_extract_endpoint_returns_extracted_names() -> None:
    app.dependency_overrides[get_ocr_service] = lambda: FakeOCRService()
    app.dependency_overrides[get_extraction_service] = lambda: FakeExtractionService()

    try:
        client = TestClient(app)
        response = client.post(
            "/api/extract",
            files={
                "pdf_file": (
                    "document.pdf",
                    create_valid_pdf(),
                    "application/pdf",
                )
            },
            data={"names": '[{"first_name":"John","last_name":"Smith"}]'},
        )

        assert response.status_code == 200
        assert response.json() == {
            "extracted_names": [
                {
                    "name": "John Smith",
                    "bounding_box": {
                        "page_number": 0,
                        "x": 72.0,
                        "y": 100.0,
                        "width": 80.0,
                        "height": 15.0,
                    },
                }
            ],
            "fuzzy_matches": [],
        }
    finally:
        app.dependency_overrides.clear()


def test_extract_endpoint_rejects_invalid_names_json() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/extract",
        files={
            "pdf_file": (
                "document.pdf",
                create_valid_pdf(),
                "application/pdf",
            )
        },
        data={"names": "not-valid-json"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "names must be a valid JSON list of name objects."
    )


def test_extract_endpoint_rejects_non_pdf_upload() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/extract",
        files={
            "pdf_file": (
                "document.txt",
                b"not a pdf",
                "text/plain",
            )
        },
        data={"names": '[{"first_name":"John","last_name":"Smith"}]'},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "The uploaded file must be a PDF."
