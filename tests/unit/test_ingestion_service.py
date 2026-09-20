"""
Module: tests.unit.test_ingestion_service
Path: tests/unit/test_ingestion_service.py
Description: Unit tests for document ingestion orchestration.
"""

from langchain_core.documents import Document

from app.models.ocr import OCRDocument, OCRPage
from app.services.ingestion_service import IngestionService


class FakeOCRService:
    """Provide deterministic OCR results for unit tests."""

    def __init__(self, document: OCRDocument) -> None:
        self.document = document
        self.received_pdf_path: str | None = None

    def extract(self, pdf_path: str) -> OCRDocument:
        self.received_pdf_path = pdf_path
        return self.document


class FakeTextChunker:
    """Provide deterministic chunks for unit tests."""

    def __init__(self) -> None:
        self.received_texts: list[str] = []

    def split_text(self, text: str) -> list[str]:
        self.received_texts.append(text)
        return [f"{text} - chunk 1", f"{text} - chunk 2"]


class FakeVectorStoreService:
    """Capture documents sent to the vector store."""

    def __init__(self) -> None:
        self.received_documents: list[Document] = []

    def add_documents(self, documents: list[Document]) -> list[str]:
        self.received_documents.extend(documents)
        return [f"id-{index}" for index in range(len(documents))]


def test_ingest_creates_page_aware_chunks_and_persists_them() -> None:
    ocr_document = OCRDocument(
        pages=[
            OCRPage(page_number=0, text="First page text", words=[]),
            OCRPage(page_number=1, text="", words=[]),
            OCRPage(page_number=2, text="Third page text", words=[]),
        ]
    )

    ocr_service = FakeOCRService(ocr_document)
    text_chunker = FakeTextChunker()
    vector_store_service = FakeVectorStoreService()

    service = IngestionService(
        ocr_service=ocr_service,
        text_chunker=text_chunker,
        vector_store_service=vector_store_service,
    )

    result = service.ingest(
        pdf_path="test.pdf",
        source="test.pdf",
    )

    assert ocr_service.received_pdf_path == "test.pdf"
    assert text_chunker.received_texts == [
        "First page text",
        "Third page text",
    ]

    assert result.chunks_stored == 4
    assert len(vector_store_service.received_documents) == 4

    documents = vector_store_service.received_documents

    assert all(
        document.metadata["document_id"] == result.document_id for document in documents
    )

    assert [document.metadata["page_number"] for document in documents] == [
        0,
        0,
        2,
        2,
    ]

    assert [document.metadata["chunk_index"] for document in documents] == [
        0,
        1,
        2,
        3,
    ]

    assert [document.metadata["source"] for document in documents] == [
        "test.pdf",
        "test.pdf",
        "test.pdf",
        "test.pdf",
    ]
