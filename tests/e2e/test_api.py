import json
import shutil

import pytest

from app.models.schemas import ExtractionResponse
from tests.conftest import MINIMAL_PDF

NAMES = json.dumps([{"first_name": "Maria", "last_name": "Gonzalez"}])


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert "x-request-id" in client.get("/health").headers


def test_extract_end_to_end(client):
    res = client.post(
        "/api/extract", files={"pdf_file": ("memo.pdf", MINIMAL_PDF)}, data={"names": NAMES}
    )
    assert res.status_code == 200, res.text
    body = ExtractionResponse.model_validate(res.json())

    names = {e.name for e in body.extracted_names}
    assert names == {"María González", "John Smith"}
    # John Smith appears on both pages, so two boxes with different pages
    smith_pages = sorted(
        e.bounding_box.page_number for e in body.extracted_names if e.name == "John Smith"
    )
    assert smith_pages == [0, 1]
    assert all(
        0 <= e.bounding_box.x <= 612 and 0 <= e.bounding_box.y <= 792 for e in body.extracted_names
    )

    assert [(m.matched_name, m.score) for m in body.fuzzy_matches] == [("Maria Gonzalez", 1.0)]


def test_extract_without_names_still_returns_boxes(client):
    res = client.post("/api/extract", files={"pdf_file": ("memo.pdf", MINIMAL_PDF)})
    assert res.status_code == 200 and res.json()["fuzzy_matches"] == []


@pytest.mark.parametrize(
    "filename, content, status",
    [
        ("notes.txt", b"just text", 415),
        ("renamed.pdf", b"still not a pdf", 415),
        ("empty.pdf", b"", 400),
        ("big.pdf", b"%PDF-" + b"0" * (2 * 1024 * 1024), 413),
    ],
)
def test_upload_validation(client, filename, content, status):
    res = client.post("/api/extract", files={"pdf_file": (filename, content)})
    assert res.status_code == status, res.text


def test_bad_names_payload(client):
    res = client.post(
        "/api/extract",
        files={"pdf_file": ("memo.pdf", MINIMAL_PDF)},
        data={"names": json.dumps([{"first_name": "", "last_name": "X"}])},
    )
    assert res.status_code == 422


def test_ingest_then_ask(client, fake_llm):
    fake_llm.answer = "María wrote it"
    first = client.post("/api/ingest", files={"pdf_file": ("memo.pdf", MINIMAL_PDF)}).json()
    second = client.post("/api/ingest", files={"pdf_file": ("memo.pdf", MINIMAL_PDF)}).json()
    assert first["status"] == "ok" and first["chunks_stored"] > 0
    assert second["chunks_stored"] == first["chunks_stored"]

    res = client.post("/api/ask", json={"question": "who wrote the memo?"})
    assert res.status_code == 200
    body = res.json()
    assert body["answer"] == "María wrote it"
    assert body["sources"] and all("memo.pdf#" in s for s in body["sources"])


def test_ask_validates_body(client):
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/ask", json={}).status_code == 422


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not installed")
def test_real_pipeline_on_sample_pdf():
    """The one test that runs the real models. Slow, but it proves the pipeline on real scans."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as real, open("sample_pdfs/meeting_minutes.pdf", "rb") as f:
        res = real.post("/api/extract", files={"pdf_file": ("meeting_minutes.pdf", f)})
    assert res.status_code == 200, res.text
    body = ExtractionResponse.model_validate(res.json())
    assert body.extracted_names, "no names found on a document that is full of them"
    assert {e.bounding_box.page_number for e in body.extracted_names} == {0, 1}
    for e in body.extracted_names:
        b = e.bounding_box
        assert 0 <= b.x and b.x + b.width <= 612 and 0 <= b.y and b.y + b.height <= 792
