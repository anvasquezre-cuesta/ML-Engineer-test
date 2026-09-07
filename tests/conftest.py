import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.core.config import Settings
from app.main import create_app
from app.services.extraction_service import ExtractionPipeline
from app.services.rag_service import RagService
from tests.fakes import FakeEmbedder, FakeLLM, FakeNer, FakeOcr, InMemoryStore, page_from_lines

MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, max_upload_mb=1, fuzzy_threshold=0.9)


@pytest.fixture
def pages():
    return [
        page_from_lines(0, ["Memo from María González to the team", "Reviewed by John Smith"]),
        page_from_lines(1, ["Signed, John Smith"]),
    ]


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(settings, pages, fake_llm):
    """App wired with fakes; no lifespan so nothing heavy loads."""
    ocr = FakeOcr(pages)
    extraction = ExtractionPipeline(ocr, FakeNer(["María González", "John Smith"]), 0.9, 0.8)
    rag = RagService(ocr, FakeEmbedder(), InMemoryStore(), fake_llm, 40, 10, 3)

    app = create_app()
    app.dependency_overrides[deps.settings] = lambda: settings
    app.dependency_overrides[deps.extraction] = lambda: extraction
    app.dependency_overrides[deps.rag] = lambda: rag
    return TestClient(app, raise_server_exceptions=False)
