from uuid import UUID

import httpx
import pymupdf
import pytest

from app.api.dependencies import get_ingestion_service
from app.main import app
from app.models.domain import OCRDocument, OCRPage
from app.models.ingestion import (
    IngestionJob,
    OCRIngestionResult,
    ValidatedPDFUpload,
)
from app.services.errors import IngestionServiceError, OCRProcessingError
from app.services.ingestion_service import DocumentIngestionService


class StubOCRService:
    def __init__(
        self,
        document: OCRDocument | None = None,
        error: Exception | None = None,
    ) -> None:
        self.document = document
        self.error = error
        self.received_content = b""

    def extract(self, pdf_content: bytes) -> OCRDocument:
        self.received_content = pdf_content
        if self.error:
            raise self.error
        assert self.document is not None
        return self.document


def make_ocr_document(page_count: int) -> OCRDocument:
    return OCRDocument(
        pages=tuple(
            OCRPage(page_number=index, text=f"Page {index}", words=())
            for index in range(page_count)
        )
    )


def make_job(page_count: int = 2) -> IngestionJob:
    return IngestionJob(
        ingestion_id=UUID("12345678-1234-5678-1234-567812345678"),
        pdf=ValidatedPDFUpload(
            filename="meeting_minutes.pdf",
            content=b"%PDF-test-content",
            page_count=page_count,
        ),
    )


def make_pdf() -> bytes:
    with pymupdf.open() as document:
        document.new_page()
        return document.tobytes()


def test_ingestion_runs_ocr_and_preserves_every_page() -> None:
    ocr_service = StubOCRService(document=make_ocr_document(page_count=2))
    service = DocumentIngestionService(ocr_service=ocr_service)
    job = make_job(page_count=2)

    result = service.run_ocr(job)

    assert result.job is job
    assert result.document.pages[0].page_number == 0
    assert result.document.pages[1].page_number == 1
    assert ocr_service.received_content == job.pdf.content


def test_ingestion_rejects_an_incomplete_ocr_result() -> None:
    service = DocumentIngestionService(
        ocr_service=StubOCRService(document=make_ocr_document(page_count=1))
    )

    with pytest.raises(IngestionServiceError, match="every PDF page"):
        service.run_ocr(make_job(page_count=2))


class FailingIngestionService:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def run_ocr(self, job: IngestionJob) -> OCRIngestionResult:
        raise self.error


async def post_with_service(service: FailingIngestionService) -> httpx.Response:
    app.dependency_overrides[get_ingestion_service] = lambda: service
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/ingest",
                files={"pdf_file": ("scan.pdf", make_pdf(), "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ingest_maps_ocr_dependency_failure_to_503() -> None:
    response = await post_with_service(
        FailingIngestionService(OCRProcessingError("tesseract unavailable"))
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "OCR service is unavailable"}


@pytest.mark.asyncio
async def test_ingest_maps_ocr_pipeline_failure_to_500() -> None:
    response = await post_with_service(
        FailingIngestionService(IngestionServiceError("missing page"))
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "document ingestion failed during OCR"}
