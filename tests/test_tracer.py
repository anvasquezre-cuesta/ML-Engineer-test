"""Tracer bullet: extract one name from one page (story 1.1).

Mocks OCR/NER providers to cover the error-mapping cases. Happy path uses
the real pipeline on sample_pdfs/company_memo.pdf.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_ocr, get_ner, OcrProvider
from app.services.ner_service import NerProvider


def build_ocr_mock(text: str = "", words: list[dict] = []):
    class OcrMockOk(OcrProvider):
        def ocr_page(self, raw, page_index, dpi=None):
            return text, words
        def page_count(self, raw):
            return 1

    return OcrMockOk()


def build_ocr_fail():
    class OcrMockFail(OcrProvider):
        def ocr_page(self, raw, page_index, dpi=None):
            raise RuntimeError("tesseract exploded")
        def page_count(self, raw):
            return 1

    return OcrMockFail()


def build_ner_mock(persons: list[str] = []):
    class NerMock(NerProvider):
        def extract_persons(self, text):
            return persons
    return NerMock()


@pytest.fixture(autouse=True)
def override_deps():
    app.dependency_overrides[get_ocr] = lambda: build_ocr_mock()
    app.dependency_overrides[get_ner] = lambda: build_ner_mock()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_extract_happy_path():
    # Real pipeline on the sample memo — clear mocks first
    app.dependency_overrides.clear()

    client = TestClient(app)
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()

    r = client.post(
        "/api/extract",
        files={"file": ("memo.pdf", pdf, "application/pdf")},
        data={"names_json": "[]"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    names = body.get("extracted_names", [])
    assert len(names) >= 1, f"Expected ≥1 name, got: {body}"
    first = names[0]
    assert first["bounding_box"]["page_number"] == 0
    # Box should be plausibly sized on a standard page
    bb = first["bounding_box"]
    assert 0 < bb["x"] < 612
    assert 0 < bb["y"] < 792
    assert 0 < bb["width"] < 612
    assert 0 < bb["height"] < 792


def test_not_pdf(client):
    r = client.post(
        "/api/extract",
        files={"file": ("notpdf.txt", b"hello", "text/plain")},
        data={"names_json": "[]"},
    )
    assert r.status_code in (422, 400)
    assert "detail" in r.json()


def test_empty(client):
    r = client.post(
        "/api/extract",
        files={"file": ("empty.pdf", b"", "application/pdf")},
        data={"names_json": "[]"},
    )
    assert r.status_code in (422, 400)
    assert "detail" in r.json()


def test_oversized(client):
    r = client.post(
        "/api/extract",
        files={"file": ("huge.pdf", b"%PDF-1.4" + b"\x00" * 25_000_000, "application/pdf")},
        data={"names_json": "[]"},
    )
    assert r.status_code in (413, 400)
    assert "detail" in r.json()


def test_no_names_found():
    # Mock OCR/NER that returns nothing
    app.dependency_overrides[get_ocr] = lambda: build_ocr_mock(text="no names here", words=[])
    app.dependency_overrides[get_ner] = lambda: build_ner_mock(persons=[])

    client = TestClient(app)
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf = f.read()

    r = client.post(
        "/api/extract",
        files={"file": ("memo.pdf", pdf, "application/pdf")},
        data={"names_json": "[]"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["extracted_names"] == []


def test_external_service_failure(client):
    app.dependency_overrides[get_ocr] = lambda: build_ocr_fail()

    r = client.post(
        "/api/extract",
        files={"file": ("memo.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"names_json": "[]"},
    )
    # OCR failure surfaces as 502 per the ExternalServiceError mapping
    assert r.status_code == 502


def test_names_json_plain_strings(client):
    # Regression: a list of plain strings used to crash the router with a 500
    words = [{"word": "Margaret", "page": 0, "x": 0, "y": 0, "width": 10, "height": 10},
             {"word": "Thompson", "page": 0, "x": 12, "y": 0, "width": 10, "height": 10}]
    app.dependency_overrides[get_ocr] = lambda: build_ocr_mock(words=words)
    app.dependency_overrides[get_ner] = lambda: build_ner_mock(["Margaret Thompson"])
    r = client.post(
        "/api/extract",
        files={"file": ("memo.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"names_json": '["Margaret Thompson", "Robert Chen", 42]'},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    extracted = {n["name"] for n in body["extracted_names"]}
    assert "Margaret Thompson" in extracted
    # "Robert Chen" merged but has no word box, so it never gets an ExtractedName
    matched = {m["matched_name"] for m in body["fuzzy_matches"]}
    assert "Margaret Thompson" in matched


def test_names_json_garbage(client):
    # Non-list / invalid JSON are tolerated as "no names provided"
    r = client.post(
        "/api/extract",
        files={"file": ("memo.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"names_json": '{"first_name": "A"}'},
    )
    assert r.status_code == 200, r.text
    assert r.json()["fuzzy_matches"] == []
