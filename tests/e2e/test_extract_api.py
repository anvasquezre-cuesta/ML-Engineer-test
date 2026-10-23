"""``POST /api/extract`` through HTTP with fake adapters: wiring, shapes and status codes."""

import json
from typing import Any

import httpx
import pytest

from tests.e2e.conftest import PDF, ClientFactory, FailingOCR

NAMES = json.dumps(
    [
        {"first_name": "Róbert", "last_name": "Chen"},  # accent on purpose
        {"first_name": "James", "last_name": "Chen"},
    ]
)


def _post(client: Any, pdf: bytes = PDF, names: str = NAMES) -> httpx.Response:
    response: httpx.Response = client.post(
        "/api/extract",
        files={"pdf_file": ("scan.pdf", pdf, "application/pdf")},
        data={"names": names},
    )
    return response


def test_returns_names_with_boxes_in_points_and_matches(make_client: ClientFactory) -> None:
    response = _post(make_client())

    assert response.status_code == 200
    body = response.json()
    assert body["extracted_names"] == [
        {
            "name": "Robert Chen",
            "bounding_box": {
                "page_number": 0,
                "x": 115.0,
                "y": 100.0,
                "width": 62.0,
                "height": 10.0,
            },
        }
    ]
    assert body["fuzzy_matches"] == [
        {"extracted_name": "Robert Chen", "matched_name": "Róbert Chen", "score": 1.0}
    ]  # "James Chen" scores 0.57 and is not returned


def test_empty_names_list_gives_names_without_matches(make_client: ClientFactory) -> None:
    body = _post(make_client(), names="[]").json()

    assert [n["name"] for n in body["extracted_names"]] == ["Robert Chen"]
    assert body["fuzzy_matches"] == []


@pytest.mark.parametrize(
    ("pdf", "names", "status", "detail"),
    [
        (b"\x89PNG\r\n\x1a\n....", NAMES, 415, "not a PDF"),
        (b"", NAMES, 422, "empty"),
        (b"%PDF-" + b"x" * 2000, NAMES, 413, "limit"),
        (PDF, "not json", 422, "'names'"),
        (PDF, '[{"first_name": "Ada"}]', 422, "'names'"),
    ],
)
def test_rejections_return_json_with_detail_and_request_id(
    make_client: ClientFactory, pdf: bytes, names: str, status: int, detail: str
) -> None:
    response = _post(make_client(max_upload_bytes=1000), pdf=pdf, names=names)

    assert response.status_code == status
    body = response.json()
    assert detail in body["detail"]
    assert body["request_id"] == response.headers["x-request-id"]


def test_missing_file_is_a_validation_error(make_client: ClientFactory) -> None:
    response = make_client().post("/api/extract", data={"names": NAMES})

    assert response.status_code == 422


def test_ocr_unavailable_is_503(make_client: ClientFactory) -> None:
    response = _post(make_client(ocr=FailingOCR()))

    assert response.status_code == 503
    assert "Tesseract" in response.json()["detail"]
