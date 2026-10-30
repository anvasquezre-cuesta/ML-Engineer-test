import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.dependencies import get_ocr_engine, get_recognizer
from app.main import app
from app.services.ocr_service import OcrEngineError
from tests.unit.test_ocr_service import FakeEngine, blank_pdf, row

ANN_LEE = [{"first_name": "ann", "last_name": "lee"}]


@pytest.fixture
def fake(monkeypatch):
    """Fake engine and recognizer injected into the app; 72 dpi means scale 1."""
    monkeypatch.setenv("OCR_DPI", "72")
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    monkeypatch.setenv("NER_MODEL", "no-such-model")  # fails if spaCy is ever loaded
    get_settings.cache_clear()
    engine = FakeEngine(
        row("Ann", left=10, top=5, width=20, height=10),
        row("Lee", left=35, top=7, width=15, height=10),
    )
    app.dependency_overrides[get_ocr_engine] = lambda: engine
    app.dependency_overrides[get_recognizer] = lambda: lambda text: [("Ann Lee", 0, 7)]
    yield engine
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def post(pdf: bytes, names: str = json.dumps(ANN_LEE)):
    files = {"pdf_file": ("doc.pdf", pdf, "application/pdf")}
    return TestClient(app).post("/api/extract", files=files, data={"names": names})


def test_ac_api_01_extracts_boxes_and_matches(fake):
    response = post(blank_pdf())

    assert response.status_code == 200
    assert response.json() == {
        "extracted_names": [
            {
                "name": "Ann Lee",
                "bounding_box": {
                    "page_number": 0,
                    "x": 10,
                    "y": 5,
                    "width": 40,
                    "height": 12,
                },
            }
        ],
        "fuzzy_matches": [
            {"extracted_name": "Ann Lee", "matched_name": "ann lee", "score": 1.0}
        ],
    }


@pytest.mark.parametrize(
    "names",
    ["not json", '[{"first_name": "", "last_name": "Lee"}]', "{}"],
    ids=["not-json", "empty-first-name", "not-a-list"],
)
def test_ac_api_02_invalid_names_never_reach_ocr(fake, names):
    response = post(blank_pdf(), names)

    assert response.status_code == 422
    assert fake.calls == 0


@pytest.mark.parametrize("data", [b"", b"not a pdf"], ids=["empty", "text"])
def test_ac_api_03_invalid_pdf_is_422(fake, data):
    response = post(data)

    assert response.status_code == 422
    assert "detail" in response.json()


def test_ac_api_04_oversized_upload_is_413(fake):
    response = post(b"0" * (1024 * 1024 + 1))

    assert response.status_code == 413
    assert fake.calls == 0


def test_ac_api_05_engine_failure_is_503(fake):
    def broken(image):
        raise OcrEngineError("Tesseract failed")

    app.dependency_overrides[get_ocr_engine] = lambda: broken

    response = post(blank_pdf())

    assert response.status_code == 503
    assert response.json() == {"detail": "Tesseract failed"}


def test_ac_log_01_json_log_with_request_id_and_no_names(fake, caplog):
    caplog.set_level(logging.INFO, logger="app")
    files = {"pdf_file": ("doc.pdf", blank_pdf(), "application/pdf")}
    data = {"names": json.dumps(ANN_LEE)}

    response = TestClient(app).post(
        "/api/extract", files=files, data=data, headers={"X-Request-ID": "abc"}
    )

    assert response.headers["X-Request-ID"] == "abc"
    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "app"]
    assert {
        "request_id": "abc",
        "pages": 1,
        "names_in": 1,
        "names_found": 1,
        "matches": 1,
    } in events
    request = next(e for e in events if "status" in e)
    assert request["request_id"] == "abc" and request["status"] == 200
    assert "ann" not in caplog.text.lower()
    assert post(blank_pdf()).headers["X-Request-ID"] not in ("", "abc")


def break_engine():
    def crash(image):
        raise RuntimeError("secret detail")

    app.dependency_overrides[get_ocr_engine] = lambda: crash


def test_ac_log_02_unhandled_error_is_logged_as_500(fake, caplog):
    caplog.set_level(logging.INFO, logger="app")
    break_engine()
    files = {"pdf_file": ("doc.pdf", blank_pdf(), "application/pdf")}

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/extract",
        files=files,
        data={"names": json.dumps(ANN_LEE)},
        headers={"X-Request-ID": "boom"},
    )

    assert response.status_code == 500
    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "app"]
    request = next(e for e in events if "status" in e)
    assert request["request_id"] == "boom" and request["status"] == 500
    assert request["ms"] >= 0
    assert "secret detail" not in caplog.text


def test_ac_log_03_unhandled_error_is_not_swallowed(fake):
    break_engine()

    with pytest.raises(RuntimeError, match="secret detail"):
        post(blank_pdf())
