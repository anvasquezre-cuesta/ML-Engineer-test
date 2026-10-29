from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.api.dependencies import Container
from app.domain.chunking import document_id_for
from app.domain.errors import OcrUnavailable, VectorStoreUnavailable
from app.infrastructure.settings import Settings
from app.main import create_app
from app.models.schemas import IngestResponse
from tests.fakes import FakeOcrEngine, FakeRasterizer, InMemoryVectorStore, line_of_words
from tests.unit.api.conftest import fake_container

PDF = b"%PDF-1.7 fake minutes"
WORDS_BY_PAGE = {
    0: line_of_words(1, "Elizabeth Park presented the results."),
    1: line_of_words(1, "The meeting was adjourned."),
}


def _client(
    make_client: Callable[..., TestClient],
    settings: Settings,
    store: InMemoryVectorStore | None = None,
    ocr: FakeOcrEngine | None = None,
) -> TestClient:
    def build(s: Settings) -> Container:
        return fake_container(
            s,
            rasterizer=FakeRasterizer(pages=2),
            ocr=ocr or FakeOcrEngine(WORDS_BY_PAGE),
            store=store,
        )

    return make_client(create_app(settings, build_container=build))


def _post(client: TestClient, pdf: bytes | None = PDF, name: str = "minutes.pdf") -> Response:
    files = {"pdf_file": (name, pdf, "application/pdf")} if pdf is not None else None
    return client.post("/api/ingest", files=files)


def test_ingest_stores_the_chunks_and_reports_how_many(
    make_client: Callable[..., TestClient], settings: Settings
) -> None:
    store = InMemoryVectorStore()

    response = _post(_client(make_client, settings, store=store))

    assert response.status_code == 200
    assert IngestResponse.model_validate(response.json()) == IngestResponse(
        status="ingested", chunks_stored=2
    )
    doc_id = document_id_for(PDF)
    assert list(store.rows) == [f"{doc_id}:0", f"{doc_id}:1"]
    assert {chunk.file_name for chunk, _ in store.rows.values()} == {"minutes.pdf"}


def test_same_pdf_twice_keeps_one_copy(
    make_client: Callable[..., TestClient], settings: Settings
) -> None:
    store = InMemoryVectorStore()
    client = _client(make_client, settings, store=store)

    first = _post(client).json()
    second = _post(client).json()

    assert first == second == {"status": "ingested", "chunks_stored": 2}
    assert len(store.rows) == 2


@pytest.mark.parametrize(
    ("pdf", "status", "code"),
    [
        (None, 422, "pdf_file_missing"),
        (b"", 400, "upload_empty"),
        (b"hello, not a pdf", 415, "upload_not_pdf"),
    ],
)
def test_invalid_uploads_are_rejected_like_extract(
    make_client: Callable[..., TestClient],
    settings: Settings,
    pdf: bytes | None,
    status: int,
    code: str,
) -> None:
    response = _post(_client(make_client, settings), pdf=pdf)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_vector_store_failure_maps_to_503(
    make_client: Callable[..., TestClient], settings: Settings
) -> None:
    store = InMemoryVectorStore(error=VectorStoreUnavailable("Vector store operation failed"))

    response = _post(_client(make_client, settings, store=store))

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "vector_store_unavailable"
    assert error["request_id"]


def test_ocr_failure_maps_to_503(
    make_client: Callable[..., TestClient], settings: Settings
) -> None:
    ocr = FakeOcrEngine(error=OcrUnavailable("Tesseract binary not found"))

    response = _post(_client(make_client, settings, ocr=ocr))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ocr_unavailable"
