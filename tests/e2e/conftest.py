"""HTTP tests run the real app wiring with fake adapters (no Tesseract, spaCy or models).

The fake document is one page; the fake OCR reads one line, at 72 DPI so one
pixel is one point:  "Approved by: Robert Chen, CTO"
"""

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.adapters.fuzzy_matcher import FuzzyMatcher
from app.container import Services
from app.core.config import LimitSettings, Settings
from app.domain.errors import OCRFailed
from app.domain.models import OcrWord, PageImage
from app.domain.protocols import LLMClient, OCREngine, PdfRenderer, VectorStore
from app.main import create_app
from app.services.ask import AskService
from app.services.chunking import WordWindowChunker
from app.services.documents import DocumentLoader
from app.services.extraction import ExtractionService
from app.services.health import Check, ReadinessService
from app.services.ingestion import IngestionService
from app.services.names import NameExtractor
from app.services.ocr import OcrService
from tests.fakes import (
    FakeEmbedder,
    FakeLLM,
    FakeNER,
    FakeOCR,
    FakeRenderer,
    InMemoryVectorStore,
    blank_page,
    ocr_word,
)

PDF = b"%PDF-1.7 fake document"

LINE = [
    ocr_word("Approved", 50, 100, 95, 110),
    ocr_word("by:", 98, 100, 112, 110),
    ocr_word("Robert", 115, 100, 148, 110),
    ocr_word("Chen,", 151, 100, 177, 110),
    ocr_word("CTO", 180, 100, 198, 110),
]


class FailingOCR:
    def recognize(self, page: PageImage) -> list[OcrWord]:
        raise OCRFailed("Tesseract is not installed or not on PATH.")


def fake_services(
    ocr: OCREngine | None = None,
    store: VectorStore | None = None,
    llm: LLMClient | None = None,
    renderer: PdfRenderer | None = None,
    checks: list[Check] | None = None,
) -> Callable[[Settings], Services]:
    def build(settings: Settings) -> Services:
        pdf_renderer = renderer or FakeRenderer([blank_page(0)])
        loader = DocumentLoader(
            pdf_renderer,
            max_bytes=settings.limits.max_upload_bytes,
            max_pages=settings.limits.max_pages,
        )
        ocr_service = OcrService(pdf_renderer, ocr or FakeOCR({0: LINE}), dpi=72)
        embedder = FakeEmbedder()
        shared_store = store if store is not None else InMemoryVectorStore()
        return Services(
            extraction=ExtractionService(
                loader,
                ocr_service,
                NameExtractor(FakeNER("Robert Chen")),
                FuzzyMatcher(threshold=settings.matching.threshold),
            ),
            ingestion=IngestionService(
                loader,
                ocr_service,
                WordWindowChunker(settings.rag.chunk_words, settings.rag.overlap_words),
                embedder,
                shared_store,
            ),
            ask=AskService(
                embedder,
                shared_store,
                llm or FakeLLM(),
                top_k=settings.rag.top_k,
                min_similarity=settings.rag.min_similarity,
                context_min_similarity=settings.rag.context_min_similarity,
            ),
            readiness=ReadinessService(
                checks
                if checks is not None
                else [Check("vector_store", lambda: f"{shared_store.count()} chunks stored")]
            ),
        )

    return build


ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client() -> Iterator[ClientFactory]:
    clients: list[TestClient] = []

    def make(
        ocr: OCREngine | None = None,
        store: VectorStore | None = None,
        llm: LLMClient | None = None,
        renderer: PdfRenderer | None = None,
        checks: list[Check] | None = None,
        max_upload_bytes: int = 1000,
        max_pages: int = 50,
        request_overhead_bytes: int = 1024 * 1024,
        raise_server_exceptions: bool = True,
    ) -> TestClient:
        limits = LimitSettings(
            max_upload_bytes=max_upload_bytes,
            max_pages=max_pages,
            request_overhead_bytes=request_overhead_bytes,
        )
        settings = Settings(_env_file=None, log_json=False, limits=limits)
        client = TestClient(
            create_app(settings, fake_services(ocr, store, llm, renderer, checks)),
            raise_server_exceptions=raise_server_exceptions,
        )
        client.__enter__()  # runs the lifespan
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)
