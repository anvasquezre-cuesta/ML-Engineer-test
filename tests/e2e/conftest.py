"""HTTP tests run the real app wiring with fake adapters (no Tesseract, no spaCy).

The fake document is one page; the fake OCR reads one line, at 72 DPI so one
pixel is one point:  "Approved by: Robert Chen, CTO"
"""

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.adapters.fuzzy_matcher import FuzzyMatcher
from app.container import Services
from app.core.config import LimitSettings, Settings
from app.domain.models import OcrWord, PageImage
from app.main import create_app
from app.services.documents import DocumentLoader
from app.services.extraction import ExtractionService
from app.services.names import NameExtractor
from app.services.ocr import OcrService
from tests.fakes import FakeNER, FakeOCR, FakeRenderer, blank_page, ocr_word

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
        from app.domain.errors import OCRFailed

        raise OCRFailed("Tesseract is not installed or not on PATH.")


def fake_services(ocr: FakeOCR | FailingOCR | None = None) -> Callable[[Settings], Services]:
    def build(settings: Settings) -> Services:
        renderer = FakeRenderer([blank_page(0)])
        loader = DocumentLoader(
            renderer,
            max_bytes=settings.limits.max_upload_bytes,
            max_pages=settings.limits.max_pages,
        )
        engine = ocr or FakeOCR({0: LINE})
        return Services(
            extraction=ExtractionService(
                loader,
                OcrService(renderer, engine, dpi=72),
                NameExtractor(FakeNER("Robert Chen")),
                FuzzyMatcher(threshold=settings.matching.threshold),
            )
        )

    return build


ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client() -> Iterator[ClientFactory]:
    clients: list[TestClient] = []

    def make(ocr: FakeOCR | FailingOCR | None = None, max_upload_bytes: int = 1000) -> TestClient:
        settings = Settings(
            _env_file=None, log_json=False, limits=LimitSettings(max_upload_bytes=max_upload_bytes)
        )
        client = TestClient(create_app(settings, fake_services(ocr)))
        client.__enter__()  # runs the lifespan
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)
