"""Upload validation & error taxonomy (story 1.4).

ATDD acceptance tests: exact HTTP status codes, exact {"detail": str} payloads,
content-based (not extension-based) PDF sniffing, temp-file lifecycle,
and no regressions in prior error-mapping behavior.
"""

import glob
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_ocr, get_ner, OcrProvider
from app.services.ner_service import NerProvider


def build_ocr_mock(text: str = "", words: list[dict] = []):
    """Mock OCR that returns predictable results."""
    class OcrMockOk(OcrProvider):
        def ocr_page(self, raw, page_index, dpi=None):
            return text, words
        def page_count(self, raw):
            return 1
    return OcrMockOk()


def build_ner_mock(persons: list[str] = []):
    """Mock NER that returns predetermined persons."""
    class NerMock(NerProvider):
        def extract_persons(self, text):
            return persons
    return NerMock()


@pytest.fixture(autouse=True)
def override_deps():
    """Override OCR/NER dependencies for all tests in this file."""
    app.dependency_overrides[get_ocr] = lambda: build_ocr_mock()
    app.dependency_overrides[get_ner] = lambda: build_ner_mock()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


# --- Helper: get list of temp PDFs before/after a request ---

def temp_pdf_files() -> list[str]:
    """List *.pdf temp files in the system temp directory."""
    return glob.glob(os.path.join(tempfile.gettempdir(), "*.pdf"))


# ============================================================================
# I/O Matrix Row 1: Real PDF misnamed .txt — content sniff, extension ignored
# ============================================================================

def test_pdf_bytes_in_txt_file_pass_validation(client):
    """Given real PDF bytes uploaded as .txt with text/plain content type,
    when POST /api/extract is called, then validation passes (200).
    """
    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf_bytes = f.read()

    # Upload real PDF bytes as a .txt file with text/plain content type
    r = client.post(
        "/api/extract",
        files={"file": ("memo.txt", pdf_bytes, "text/plain")},
        data={"names_json": "[]"},
    )
    # Should pass validation — the content sniff detects %PDF- magic bytes
    assert r.status_code == 200, f"Expected 200 for real PDF in .txt wrapper, got {r.status_code}: {r.text}"
    body = r.json()
    # Body structure check
    assert "extracted_names" in body


# ============================================================================
# I/O Matrix Row 2: Renamed text file — non-PDF content as .pdf → 422
# ============================================================================

def test_text_content_as_pdf_returns_422(client):
    """Given text content uploaded as .pdf, when POST /api/extract is called,
    then response is 422 with {"detail": str}.
    """
    r = client.post(
        "/api/extract",
        files={"file": ("notpdf.pdf", b"This is plain text, not a PDF", "application/pdf")},
        data={"names_json": "[]"},
    )
    assert r.status_code == 422, f"Expected 422 for non-PDF content as .pdf, got {r.status_code}: {r.text}"
    body = r.json()
    assert "detail" in body, "Response must contain 'detail' field"
    assert isinstance(body["detail"], str), "'detail' must be a string"
    # Should reference the PDF validation failure
    assert body["detail"]


# ============================================================================
# I/O Matrix Row 3: Empty upload → 422
# ============================================================================

def test_empty_file_returns_422(client):
    """Given a 0-byte upload, when POST /api/extract is called,
    then response is 422 with {"detail": str}.
    """
    r = client.post(
        "/api/extract",
        files={"file": ("empty.pdf", b"", "application/pdf")},
        data={"names_json": "[]"},
    )
    assert r.status_code == 422, f"Expected 422 for empty upload, got {r.status_code}: {r.text}"
    body = r.json()
    assert "detail" in body, "Response must contain 'detail' field"
    assert isinstance(body["detail"], str), "'detail' must be a string"


# ============================================================================
# I/O Matrix Row 4: Oversized upload → 413
# ============================================================================

def test_oversized_upload_returns_413(client):
    """Given an upload exceeding max_upload_bytes (20 MB default),
    when POST /api/extract is called, then response is 413 with {"detail": str}.
    """
    # Create a payload over 20 MB (21 MB)
    huge = b"%PDF-1.4" + b"\x00" * 21_000_000

    r = client.post(
        "/api/extract",
        files={"file": ("huge.pdf", huge, "application/pdf")},
        data={"names_json": "[]"},
    )
    assert r.status_code == 413, f"Expected 413 for oversized upload, got {r.status_code}: {r.text}"
    body = r.json()
    assert "detail" in body, "Response must contain 'detail' field"
    assert isinstance(body["detail"], str), "'detail' must be a string"


# ============================================================================
# I/O Matrix Row 5: No temp residue after happy-path request
# ============================================================================

def test_no_temp_file_residue_after_request(client):
    """Given a completed happy-path request, when the temp directory is
    inspected, then it holds no more *.pdf temp files than before the request.
    """
    # Snapshot temp files before
    before = set(temp_pdf_files())

    with open("sample_pdfs/company_memo.pdf", "rb") as f:
        pdf_bytes = f.read()

    # Happy path request (with mocked OCR/NER)
    r = client.post(
        "/api/extract",
        files={"file": ("memo.pdf", pdf_bytes, "application/pdf")},
        data={"names_json": "[]"},
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    # Snapshot temp files after
    after = set(temp_pdf_files())

    # Any new temp files should have been cleaned up
    new_files = after - before
    assert len(new_files) == 0, (
        f"Temp PDF files leaked after request: {list(new_files)}"
    )


# ============================================================================
# I/O Matrix Row 6: Corrupt after sniff — starts %PDF- but not parseable → 502
# ============================================================================

def test_corrupt_pdf_after_sniff_returns_502():
    """Given a file starting with %PDF- but not parseable, when POST
    /api/extract is called, then response is 502 (existing behavior unchanged).
    """
    # Clear mocks for this test — use real pipeline
    app.dependency_overrides.clear()

    client = TestClient(app)

    # Starts with %PDF- magic but is otherwise garbage
    fake_pdf = b"%PDF-1.4 garbage not a real pdf"

    r = client.post(
        "/api/extract",
        files={"file": ("fake.pdf", fake_pdf, "application/pdf")},
        data={"names_json": "[]"},
    )
    # Must be 502, not 422 — existing story-1.1 behavior
    assert r.status_code == 502, f"Expected 502 for corrupt PDF after sniff, got {r.status_code}: {r.text}"
    body = r.json()
    assert "detail" in body
    assert isinstance(body["detail"], str)


# ============================================================================
# Regression: ensure prior error-mapping behavior is preserved
# ============================================================================

def test_tracer_notpdf_still_fails(client):
    """Regression: the original not-PDF check still rejects non-PDFs."""
    r = client.post(
        "/api/extract",
        files={"file": ("notpdf.txt", b"hello", "text/plain")},
        data={"names_json": "[]"},
    )
    assert r.status_code in (422, 400), f"Expected 422/400 for non-PDF, got {r.status_code}"
    assert "detail" in r.json()


def test_tracer_empty_still_fails(client):
    """Regression: the original empty check still rejects empty uploads."""
    r = client.post(
        "/api/extract",
        files={"file": ("empty.pdf", b"", "application/pdf")},
        data={"names_json": "[]"},
    )
    assert r.status_code in (422, 400), f"Expected 422/400 for empty, got {r.status_code}"
    assert "detail" in r.json()


def test_tracer_oversized_still_fails(client):
    """Regression: the original oversized check still rejects large uploads."""
    r = client.post(
        "/api/extract",
        files={"file": ("huge.pdf", b"%PDF-1.4" + b"\x00" * 25_000_000, "application/pdf")},
        data={"names_json": "[]"},
    )
    assert r.status_code in (413, 400), f"Expected 413/400 for oversized, got {r.status_code}"
    assert "detail" in r.json()
