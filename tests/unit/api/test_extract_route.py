import json
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.api.dependencies import Container
from app.domain.errors import OcrUnavailable, PdfUnreadable
from app.infrastructure.settings import Settings
from app.main import create_app
from app.models.schemas import ExtractionResponse
from tests.fakes import FakeOcrEngine, FakeRasterizer, FakeRecognizer, line_of_words
from tests.unit.api.conftest import fake_container

PDF = b"%PDF-1.7 fake"
PAGE_0 = line_of_words(1, "From: Margaret Thompson, CEO")
PAGE_1 = line_of_words(3, "Approved by María García today")


def _client(
    make_client: Callable[..., TestClient],
    settings: Settings,
    rasterizer: FakeRasterizer | None = None,
    ocr: FakeOcrEngine | None = None,
) -> TestClient:
    def build(s: Settings) -> Container:
        return fake_container(
            s,
            rasterizer=rasterizer or FakeRasterizer(pages=2),
            ocr=ocr or FakeOcrEngine({0: PAGE_0, 1: PAGE_1}),
            recognizer=FakeRecognizer(["Margaret Thompson", "María García"]),
        )

    return make_client(create_app(settings, build_container=build))


def _post(client: TestClient, names: object = None, pdf: bytes | None = PDF) -> Response:
    files = {"pdf_file": ("doc.pdf", pdf, "application/pdf")} if pdf is not None else None
    data = None
    if names is not None:
        data = {"names": names if isinstance(names, str) else json.dumps(names)}
    return client.post("/api/extract", files=files, data=data)


def test_occurrences_and_matches_are_mapped_to_the_contract(
    make_client: Callable[..., TestClient], settings: Settings
) -> None:
    client = _client(make_client, settings)

    response = _post(client, [{"first_name": "Maria", "last_name": "Garcia"}])

    assert response.status_code == 200
    body = ExtractionResponse.model_validate(response.json())
    assert [(e.name, e.bounding_box.page_number) for e in body.extracted_names] == [
        ("Margaret Thompson", 0),
        ("María García", 1),
    ]
    first = body.extracted_names[0].bounding_box
    assert (first.x, first.y, first.height) == (PAGE_0[1].box.x, PAGE_0[1].box.y, 12.0)
    assert first.width == PAGE_0[2].box.right - PAGE_0[1].box.x
    assert [(m.extracted_name, m.matched_name, m.score) for m in body.fuzzy_matches] == [
        ("María García", "Maria Garcia", 1.0)
    ]


def test_missing_names_field_means_no_names_to_check(
    make_client: Callable[..., TestClient], settings: Settings
) -> None:
    response = _post(_client(make_client, settings))

    assert response.status_code == 200
    assert response.json()["fuzzy_matches"] == []
    assert len(response.json()["extracted_names"]) == 2


@pytest.mark.parametrize("names", ["not json", '{"first_name": "A"}', '[{"first_name": "Ana"}]'])
def test_malformed_names_are_rejected(
    make_client: Callable[..., TestClient], settings: Settings, names: str
) -> None:
    response = _post(_client(make_client, settings), names)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "names_invalid"


def test_missing_file_is_rejected(
    make_client: Callable[..., TestClient], settings: Settings
) -> None:
    response = _post(_client(make_client, settings), [], pdf=None)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "pdf_file_missing"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (OcrUnavailable("Tesseract binary not found: tesseract"), 503, "ocr_unavailable"),
        (PdfUnreadable("The file could not be parsed as a PDF"), 422, "pdf_unreadable"),
    ],
)
def test_pipeline_errors_map_to_status(
    make_client: Callable[..., TestClient],
    settings: Settings,
    error: Exception,
    status: int,
    code: str,
) -> None:
    client = _client(make_client, settings, ocr=FakeOcrEngine(error=error))

    response = _post(client, [])

    assert response.status_code == status
    error_body = response.json()["error"]
    assert error_body["code"] == code
    assert error_body["request_id"]
