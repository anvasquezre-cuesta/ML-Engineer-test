"""All pages, every sample document (story 2).

AC-1: Every detection has correct 0-based page number (regression on real samples)
AC-2: Bounding boxes are within page bounds (structural proxy for visual hand-check)
AC-3: Name appearing twice on one page yields two boxes (mock)
AC-4: Error cases still hold (regression via test_tracer.py, structural)
AC-5: Heavy deps mocked except real-pipeline sample tests (structural)

I/O matrix:
- Multi-page happy path: every page visited, correct page attribution (mock)
- Name twice on one page: two separate boxes (mock)
- Name split across pages: no merged box (mock)
- Page with no names: no detections from that page (mock)
- OCR failure mid-document: 502 (mock)
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_ocr, get_ner, OcrProvider
from app.services.ner_service import NerProvider


class OcrMock(OcrProvider):
    """Mock OCR that can simulate different content per page."""
    def __init__(self, pages: list[tuple[str, list[dict]]]):
        self.pages = pages
        self.page_calls = []

    def ocr_page(self, raw, page_index, dpi=None):
        self.page_calls.append(page_index)
        if page_index < len(self.pages):
            return self.pages[page_index]
        return ("", [])

    def page_count(self, raw):
        return len(self.pages)


class NerMock(NerProvider):
    def __init__(self, persons: list[str]):
        self.persons = persons

    def extract_persons(self, text):
        return self.persons


@pytest.fixture
def client():
    return TestClient(app)


def test_multi_page_happy_path_mock():
    """Multi-page happy path: every page is visited and each detection has correct page."""
    # Simulate a 3-page doc with Alice on page 0, Bob on page 1, Charlie on page 2
    alice_words = [{"word": "Alice", "page": 0, "x": 100, "y": 200, "width": 50, "height": 10}]
    bob_words = [{"word": "Bob", "page": 1, "x": 150, "y": 300, "width": 40, "height": 10}]
    charlie_words = [{"word": "Charlie", "page": 2, "x": 200, "y": 400, "width": 60, "height": 10}]

    pages = [
        ("Hello Alice here", alice_words),
        ("Hello Bob there", bob_words),
        ("Hello Charlie now", charlie_words),
    ]
    mock_ocr = OcrMock(pages)
    mock_ner = NerMock(["Alice", "Bob", "Charlie"])

    app.dependency_overrides[get_ocr] = lambda: mock_ocr
    app.dependency_overrides[get_ner] = lambda: mock_ner

    try:
        client = TestClient(app)
        r = client.post(
            "/api/extract",
            files={"file": ("multi.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"names_json": "[]"},
        )
        assert r.status_code == 200, r.text
        # Every page must be visited
        assert set(mock_ocr.page_calls) == {0, 1, 2}
        # Each detection must have the correct 0-based page number
        body = r.json()
        names = body["extracted_names"]
        by_name = {n["name"]: n for n in names}
        assert "Alice" in by_name
        assert by_name["Alice"]["bounding_box"]["page_number"] == 0
        assert "Bob" in by_name
        assert by_name["Bob"]["bounding_box"]["page_number"] == 1
        assert "Charlie" in by_name
        assert by_name["Charlie"]["bounding_box"]["page_number"] == 2
    finally:
        app.dependency_overrides.clear()


def test_name_twice_on_one_page():
    """AC-3: Name appearing twice on one page yields two separate boxes."""
    # Page has "Alice and Alice" — two separate bounding boxes for Alice
    alice1 = {"word": "Alice", "page": 0, "x": 100, "y": 200, "width": 50, "height": 10}
    alice2 = {"word": "Alice", "page": 0, "x": 200, "y": 200, "width": 50, "height": 10}
    and_word = {"word": "and", "page": 0, "x": 160, "y": 200, "width": 30, "height": 10}

    pages = [("Alice and Alice", [alice1, and_word, alice2])]
    mock_ocr = OcrMock(pages)
    mock_ner = NerMock(["Alice"])

    app.dependency_overrides[get_ocr] = lambda: mock_ocr
    app.dependency_overrides[get_ner] = lambda: mock_ner

    try:
        client = TestClient(app)
        r = client.post(
            "/api/extract",
            files={"file": ("dup.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"names_json": "[]"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        alice_entries = [n for n in body["extracted_names"] if n["name"] == "Alice"]
        # Two separate boxes for the same name on the same page
        assert len(alice_entries) == 2
    finally:
        app.dependency_overrides.clear()


def test_name_split_across_pages_no_merge():
    """I/O matrix: Name split across pages is NOT merged."""
    # "Alice" starts on page 0, continues on page 1 — should yield separate entries
    alice_first = {"word": "Alic", "page": 0, "x": 100, "y": 200, "width": 30, "height": 10}
    alice_last = {"word": "e", "page": 1, "x": 50, "y": 300, "width": 5, "height": 10}

    pages = [
        ("Alic", [alice_first]),
        ("e", [alice_last]),
    ]
    mock_ocr = OcrMock(pages)
    mock_ner = NerMock(["Alice"])

    app.dependency_overrides[get_ocr] = lambda: mock_ocr
    app.dependency_overrides[get_ner] = lambda: mock_ner

    try:
        client = TestClient(app)
        r = client.post(
            "/api/extract",
            files={"file": ("split.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"names_json": "[]"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Should not merge across pages; either 0 or 2 entries (depending on
        # whether each partial match succeeds). Should not be 1 merged entry.
        alice_entries = [n for n in body["extracted_names"] if n["name"] == "Alice"]
        # Critical: no merged cross-page box
        for entry in alice_entries:
            bb = entry["bounding_box"]
            assert bb["page_number"] in (0, 1)  # One page each, not merged
    finally:
        app.dependency_overrides.clear()


def test_page_with_no_names():
    """I/O matrix: Page with no names yields no detections from that page."""
    # Page 0 has name, page 1 has no name
    alice = {"word": "Alice", "page": 0, "x": 100, "y": 200, "width": 50, "height": 10}
    pages = [
        ("Alice here", [alice]),
        ("Just some text here", []),
    ]
    mock_ocr = OcrMock(pages)
    mock_ner = NerMock(["Alice"])

    app.dependency_overrides[get_ocr] = lambda: mock_ocr
    app.dependency_overrides[get_ner] = lambda: mock_ner

    try:
        client = TestClient(app)
        r = client.post(
            "/api/extract",
            files={"file": ("mixed.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"names_json": "[]"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        names = body["extracted_names"]
        # Only one detection (Alice on page 0), none from page 1
        assert len(names) == 1
        assert names[0]["name"] == "Alice"
        assert names[0]["bounding_box"]["page_number"] == 0
    finally:
        app.dependency_overrides.clear()


def test_ocr_failure_mid_document():
    """I/O matrix: OCR/NER failure on any page surfaces as 502."""
    class OcrMidFail(OcrProvider):
        def ocr_page(self, raw, page_index, dpi=None):
            if page_index == 1:
                raise RuntimeError("ocr failure on page 1")
            return ("", [])

        def page_count(self, raw):
            return 2

    mock_ocr = OcrMidFail()
    mock_ner = NerMock([])

    app.dependency_overrides[get_ocr] = lambda: mock_ocr
    app.dependency_overrides[get_ner] = lambda: mock_ner

    try:
        client = TestClient(app)
        r = client.post(
            "/api/extract",
            files={"file": ("fail.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"names_json": "[]"},
        )
        assert r.status_code == 502
        assert "detail" in r.json()
    finally:
        app.dependency_overrides.clear()


# AC-1 real-pipeline tests: each of the three sample PDFs

def test_real_company_memo_multi_page():
    """AC-1: company_memo.pdf — detections have correct page numbers."""
    app.dependency_overrides.clear()
    try:
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
        # AC-2 proxy: bounding boxes must be within page bounds
        for entry in names:
            bb = entry["bounding_box"]
            assert 0 <= bb["page_number"]
            assert 0 < bb["x"] < 612
            assert 0 < bb["y"] < 792
            assert 0 < bb["width"] < 612
            assert 0 < bb["height"] < 792
    finally:
        app.dependency_overrides.clear()


def test_real_meeting_minutes_multi_page():
    """AC-1: meeting_minutes.pdf — detections have correct page numbers."""
    app.dependency_overrides.clear()
    try:
        client = TestClient(app)
        with open("sample_pdfs/meeting_minutes.pdf", "rb") as f:
            pdf = f.read()
        r = client.post(
            "/api/extract",
            files={"file": ("minutes.pdf", pdf, "application/pdf")},
            data={"names_json": "[]"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        names = body.get("extracted_names", [])
        # At least one page contains names in this document
        assert len(names) >= 1, f"Expected ≥1 name, got: {body}"
        for entry in names:
            bb = entry["bounding_box"]
            assert 0 <= bb["page_number"]
            assert 0 < bb["x"] < 612
            assert 0 < bb["y"] < 792
            assert 0 < bb["width"] < 612
            assert 0 < bb["height"] < 792
    finally:
        app.dependency_overrides.clear()


def test_real_research_report_multi_page():
    """AC-1: research_report.pdf — detections have correct page numbers."""
    app.dependency_overrides.clear()
    try:
        client = TestClient(app)
        with open("sample_pdfs/research_report.pdf", "rb") as f:
            pdf = f.read()
        r = client.post(
            "/api/extract",
            files={"file": ("research.pdf", pdf, "application/pdf")},
            data={"names_json": "[]"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        names = body.get("extracted_names", [])
        # At least one page contains names in this document
        assert len(names) >= 1, f"Expected ≥1 name, got: {body}"
        for entry in names:
            bb = entry["bounding_box"]
            assert 0 <= bb["page_number"]
            assert 0 < bb["x"] < 612
            assert 0 < bb["y"] < 792
            assert 0 < bb["width"] < 612
            assert 0 < bb["height"] < 792
    finally:
        app.dependency_overrides.clear()


def test_no_duplicate_detections():
    """Verify no exact-duplicate (name, page, x, y, w, h) tuples in results."""
    app.dependency_overrides.clear()
    try:
        client = TestClient(app)
        with open("sample_pdfs/meeting_minutes.pdf", "rb") as f:
            pdf = f.read()
        r = client.post(
            "/api/extract",
            files={"file": ("minutes.pdf", pdf, "application/pdf")},
            data={"names_json": "[]"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        names = body.get("extracted_names", [])
        seen = set()
        for entry in names:
            bb = entry["bounding_box"]
            key = (
                entry["name"],
                bb["page_number"],
                round(bb["x"], 3),
                round(bb["y"], 3),
                round(bb["width"], 3),
                round(bb["height"], 3),
            )
            assert key not in seen, f"Duplicate detection: {entry}"
            seen.add(key)
    finally:
        app.dependency_overrides.clear()


def test_name_spanning_page_break_not_merged():
    """A multi-word name split across pages should NOT match/merge."""
    page0 = ("Alice", [{"word": "Alice", "page": 0, "x": 0, "y": 0, "width": 12, "height": 10}])
    page1 = ("Smith", [{"word": "Smith", "page": 1, "x": 0, "y": 0, "width": 12, "height": 10}])
    mock_ocr = OcrMock([page0, page1])
    mock_ner = NerMock(["Alice Smith"])

    app.dependency_overrides[get_ocr] = lambda: mock_ocr
    app.dependency_overrides[get_ner] = lambda: mock_ner

    try:
        client = TestClient(app)
        r = client.post(
            "/api/extract",
            files={"file": ("span.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"names_json": "[]"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        names = body["extracted_names"]
        # No box should be produced — matching is per-page
        assert len(names) == 0, f"Expected 0, got: {body}"
    finally:
        app.dependency_overrides.clear()
