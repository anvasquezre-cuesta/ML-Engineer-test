"""Exercise the real router with controlled adapters and real multipart bodies."""

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_extraction_service
from app.api.extract import router
from app.core.config import Settings
from app.core.request_limits import ExtractionBodyLimitMiddleware
from app.main import app as actual_app, lifespan
from app.models.document import OCRDocument, OCRPage, OCRWord, WordBox
from app.models.extraction import PersonSpan
from app.services.extraction_service import ExtractionService
from app.services.ner_service import NERBusyError, NERModelUnavailableError, NERTimeoutError
from app.services.ocr_service import InvalidPDFError, OCRBusyError, OCRDocumentTimeoutError, PDFPageCountError, PDFPageTooLargeError


def document():
    def page(number):
        return OCRPage(number, 200, 200, "Alice Smith", (
            OCRWord("Alice", WordBox(10, 20, 30, 10), 0, 5, 1, 1, 1, 90),
            OCRWord("Smith", WordBox(45, 20, 25, 10), 6, 11, 1, 1, 1, 90),
        ))
    return OCRDocument((page(0), page(1)))


class FakeOCR:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    async def extract_stream_async(self, stream):
        self.calls += 1
        await stream.read()
        if self.error:
            raise self.error
        return document()


class FakeNER:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    async def detect_pages(self, pages):
        self.calls += 1
        if self.error:
            raise self.error
        return [[PersonSpan("Alice Smith", 0, 11)] for _ in pages]


def make_app(monkeypatch, settings=None, ocr=None, ner=None):
    settings = settings or Settings()
    ocr = ocr or FakeOCR()
    ner = ner or FakeNER()
    monkeypatch.setattr("app.api.extract.get_settings", lambda: settings)
    app = FastAPI()
    app.add_middleware(
        ExtractionBodyLimitMiddleware, max_request_bytes=settings.max_request_bytes,
        max_in_flight=settings.extract_max_in_flight,
        upload_timeout_seconds=settings.extract_upload_timeout_seconds,
    )
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_extraction_service] = lambda: ExtractionService(ocr, ner, settings)
    return app, ocr, ner


def fields(names='[{"first_name":"alice","last_name":"smith"}]', data=b"pdf"):
    return {"pdf_file": ("sample.pdf", data, "application/pdf"), "names": (None, names)}


def test_endpoint_processes_each_page_with_one_ocr_and_distinct_locations(monkeypatch):
    app, ocr, ner = make_app(monkeypatch)
    with TestClient(app) as client:
        response = client.post("/api/extract", files=fields())
    assert response.status_code == 200
    body = response.json()
    assert [item["bounding_box"]["page_number"] for item in body["extracted_names"]] == [0, 1]
    assert all(item["bounding_box"]["width"] == 60 for item in body["extracted_names"])
    assert body["fuzzy_matches"] == [{"extracted_name": "Alice Smith", "matched_name": "alice smith", "score": 1.0}]
    assert (ocr.calls, ner.calls) == (1, 1)


def test_disabled_name_recovery_is_identical_and_never_called(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Disabled recovery must not be called")
    monkeypatch.setattr("app.services.extraction_service.recover_names", forbidden)
    monkeypatch.delenv("NER_NAME_RECOVERY_PASSES", raising=False)
    default, _, _ = make_app(monkeypatch, Settings())
    explicit, _, _ = make_app(monkeypatch, Settings(ner_name_recovery_passes=0))
    with TestClient(default) as first, TestClient(explicit) as second:
        baseline = first.post("/api/extract", files=fields())
        disabled = second.post("/api/extract", files=fields())
    assert baseline.status_code == disabled.status_code == 200
    assert baseline.content == disabled.content


@pytest.mark.parametrize("level", [1, 2, 3])
def test_recovery_finds_ocr_occurrence_missed_by_ner_without_rerunning_either(monkeypatch, level):
    class MissingSecondNER(FakeNER):
        async def detect_pages(self, pages):
            self.calls += 1
            return [[PersonSpan("Alice Smith", 0, 11)], []]

    ocr, ner = FakeOCR(), MissingSecondNER()
    app, _, _ = make_app(monkeypatch, Settings(ner_name_recovery_passes=level), ocr=ocr, ner=ner)
    with TestClient(app) as client:
        response = client.post("/api/extract", files=fields())
    assert response.status_code == 200
    found = response.json()["extracted_names"]
    assert [(item["name"], item["bounding_box"]["page_number"]) for item in found] == [
        ("Alice Smith", 0), ("Alice Smith", 1),
    ]
    assert all(item["bounding_box"]["width"] == 60 for item in found)
    assert ocr.calls == ner.calls == 1


def test_recovery_limit_is_mapped_to_413_without_partial_results(monkeypatch):
    class MissingSecondNER(FakeNER):
        async def detect_pages(self, pages):
            self.calls += 1
            return [[PersonSpan("Alice Smith", 0, 11)], []]

    app, _, _ = make_app(monkeypatch, Settings(ner_name_recovery_passes=1, max_extracted_names=1), ner=MissingSecondNER())
    with TestClient(app) as client:
        response = client.post("/api/extract", files=fields())
    assert response.status_code == 413 and "Alice" not in response.text


@pytest.mark.parametrize("threshold,expected_matches", [
    (0.90, {"Alice Smith", "Alice Smitx"}), (1.0, {"Alice Smith"}),
])
def test_recovery_is_independent_of_query_threshold_and_preserves_schema(monkeypatch, threshold, expected_matches):
    class VariantOCR(FakeOCR):
        async def extract_stream_async(self, stream):
            self.calls += 1
            text = "Alice Smith Alice Smitx"
            words = (
                OCRWord("Alice", WordBox(10, 20, 20, 10), 0, 5, 1, 1, 1, 90),
                OCRWord("Smith", WordBox(35, 20, 20, 10), 6, 11, 1, 1, 1, 90),
                OCRWord("Alice", WordBox(90, 20, 20, 10), 12, 17, 1, 1, 1, 90),
                OCRWord("Smitx", WordBox(115, 20, 20, 10), 18, 23, 1, 1, 1, 90),
            )
            return OCRDocument((OCRPage(0, 300, 200, text, words),))

    class FirstNER(FakeNER):
        async def detect_pages(self, pages):
            self.calls += 1
            return [[PersonSpan("Alice Smith", 0, 11)]]

    app, _, _ = make_app(monkeypatch, Settings(ner_name_recovery_passes=2, fuzzy_threshold=threshold),
                         ocr=VariantOCR(), ner=FirstNER())
    with TestClient(app) as client:
        result = client.post("/api/extract", files=fields()).json()
    assert set(result) == {"extracted_names", "fuzzy_matches"}
    assert [item["name"] for item in result["extracted_names"]] == ["Alice Smith", "Alice Smitx"]
    assert {item["extracted_name"] for item in result["fuzzy_matches"]} == expected_matches


def test_openapi_documents_the_actual_multipart_contract(monkeypatch):
    app, _, _ = make_app(monkeypatch)
    request = app.openapi()["paths"]["/api/extract"]["post"]["requestBody"]
    schema = request["content"]["multipart/form-data"]["schema"]
    assert set(schema["required"]) == {"pdf_file", "names"}
    assert schema["properties"]["pdf_file"]["format"] == "binary"


def test_empty_query_list_is_valid(monkeypatch):
    app, _, _ = make_app(monkeypatch)
    with TestClient(app) as client:
        response = client.post("/api/extract", files=fields("[]"))
    assert response.status_code == 200 and response.json()["fuzzy_matches"] == []


@pytest.mark.parametrize("names", ["not json", "{}", '[{"first_name":"  ","last_name":"Doe"}]'])
def test_invalid_names_are_rejected_before_ocr(monkeypatch, names):
    app, ocr, _ = make_app(monkeypatch)
    with TestClient(app) as client:
        response = client.post("/api/extract", files=fields(names))
    assert response.status_code == 422 and ocr.calls == 0


def test_names_and_pdf_limits_are_enforced_during_parsing(monkeypatch):
    settings = Settings(max_names_bytes=8, max_upload_bytes=4, max_request_bytes=4096)
    app, ocr, _ = make_app(monkeypatch, settings)
    with TestClient(app) as client:
        assert client.post("/api/extract", files=fields(" " * 9, b"pdf")).status_code == 413
        assert client.post("/api/extract", files=fields("[]", b"12345")).status_code == 413
        assert client.post("/api/extract", files=fields("[]", b"1234")).status_code == 200
    assert ocr.calls == 1


@pytest.mark.parametrize("declared", [None, "1"])
def test_real_route_counts_fragmented_body_when_length_is_missing_or_false(monkeypatch, declared):
    body = (b'--boundary\r\nContent-Disposition: form-data; name="pdf_file"; filename="x.pdf"\r\n'
            b'Content-Type: application/pdf\r\n\r\npdf\r\n'
            b'--boundary\r\nContent-Disposition: form-data; name="names"\r\n\r\n[]\r\n--boundary--\r\n')
    app, ocr, _ = make_app(monkeypatch, Settings(max_request_bytes=len(body) - 1))
    chunks = [body[index:index + 11] for index in range(0, len(body), 11)] + [b"not-read"]
    received = []

    async def stream():
        for chunk in chunks:
            received.append(chunk)
            yield chunk

    async def run():
        headers = {"Content-Type": "multipart/form-data; boundary=boundary"}
        if declared is not None:
            headers["Content-Length"] = declared
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/extract", content=stream(), headers=headers)

    response = asyncio.run(run())
    assert response.status_code == 413 and ocr.calls == 0
    assert received == chunks[:-1]


def test_very_large_text_field_is_413_not_framework_400(monkeypatch):
    settings = Settings(max_names_bytes=64 * 1024, max_request_bytes=2 * 1024 * 1024)
    app, ocr, _ = make_app(monkeypatch, settings)
    with TestClient(app) as client:
        response = client.post("/api/extract", files=fields("x" * (1024 * 1024 + 1)))
    assert response.status_code == 413 and ocr.calls == 0


@pytest.mark.parametrize("files", [
    {"pdf_file": ("x.pdf", b"pdf")}, {"names": (None, "[]")},
    {"pdf_file": (None, "not-a-file"), "names": (None, "[]")},
    {"pdf_file": ("x.pdf", b"pdf"), "names": ("names.json", b"[]")},
])
def test_missing_or_wrong_parts_are_rejected(monkeypatch, files):
    app, ocr, _ = make_app(monkeypatch)
    with TestClient(app) as client:
        response = client.post("/api/extract", files=files)
    assert response.status_code == 422 and ocr.calls == 0


def test_missing_final_multipart_boundary_is_rejected_and_file_closed(monkeypatch):
    import starlette.formparsers

    created = []
    original = starlette.formparsers.SpooledTemporaryFile

    def tracked(*args, **kwargs):
        result = original(*args, **kwargs)
        created.append(result)
        return result

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", tracked)
    app, ocr, _ = make_app(monkeypatch)
    incomplete = (b'--boundary\r\nContent-Disposition: form-data; name="pdf_file"; filename="x.pdf"\r\n'
                  b'Content-Type: application/pdf\r\n\r\npartial')
    with TestClient(app) as client:
        response = client.post("/api/extract", content=incomplete, headers={"Content-Type": "multipart/form-data; boundary=boundary"})
    assert response.status_code == 422 and ocr.calls == 0
    assert len(created) == 1 and created[0].closed


@pytest.mark.parametrize("error,status", [
    (InvalidPDFError("private"), 400), (PDFPageTooLargeError("private"), 413), (PDFPageCountError("private"), 413),
    (OCRBusyError("private"), 503), (OCRDocumentTimeoutError("private"), 504),
])
def test_ocr_errors_have_safe_http_responses(monkeypatch, error, status):
    app, _, _ = make_app(monkeypatch, ocr=FakeOCR(error))
    with TestClient(app) as client:
        response = client.post("/api/extract", files=fields())
    assert response.status_code == status
    assert "private" not in response.text


@pytest.mark.parametrize("error,status", [
    (NERBusyError("private"), 503), (NERModelUnavailableError("private"), 503),
    (NERTimeoutError("private"), 504),
])
def test_ner_errors_have_safe_http_responses(monkeypatch, error, status):
    app, _, _ = make_app(monkeypatch, ner=FakeNER(error))
    with TestClient(app) as client:
        response = client.post("/api/extract", files=fields())
    assert response.status_code == status and "private" not in response.text


def test_extraction_complexity_limits_reject_instead_of_truncating(monkeypatch):
    app, _, _ = make_app(monkeypatch, Settings(max_extracted_names=1))
    with TestClient(app) as client:
        assert client.post("/api/extract", files=fields()).status_code == 413
    app, _, _ = make_app(monkeypatch, Settings(max_fuzzy_comparisons=1))
    names = json.dumps([{"first_name": "Alice", "last_name": "Smith"}, {"first_name": "Bob", "last_name": "Doe"}])
    with TestClient(app) as client:
        assert client.post("/api/extract", files=fields(names)).status_code == 413
    app, _, _ = make_app(monkeypatch, Settings(max_name_chars=4))
    with TestClient(app) as client:
        assert client.post("/api/extract", files=fields()).status_code == 413
    app, _, _ = make_app(monkeypatch, Settings(max_fuzzy_work_units=120))
    with TestClient(app) as client:
        assert client.post("/api/extract", files=fields()).status_code == 413


def test_admission_rejects_before_reading_second_upload(monkeypatch):
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()

        class SlowOCR(FakeOCR):
            async def extract_stream_async(self, stream):
                started.set()
                await finish.wait()
                return document()

        settings = Settings(extract_max_in_flight=1)
        app, _, _ = make_app(monkeypatch, settings, ocr=SlowOCR())
        received = []

        async def body():
            received.append(True)
            yield b"should not be read"

        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                first = asyncio.create_task(client.post("/api/extract", files=fields("[]")))
                await asyncio.wait_for(started.wait(), timeout=2)
                second = await client.post("/api/extract", content=body())
                assert second.status_code == 503 and received == []
                assert second.headers["retry-after"] == "1"
                finish.set()
                assert (await first).status_code == 200
        finally:
            finish.set()

    asyncio.run(run())


def test_health_remains_responsive_during_actual_extraction_route(monkeypatch):
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()

        class WaitingNER(FakeNER):
            async def detect_pages(self, pages):
                started.set()
                await finish.wait()
                return [[PersonSpan("Alice Smith", 0, 11)] for _ in pages]

        service = ExtractionService(FakeOCR(), WaitingNER(), Settings())
        monkeypatch.setitem(actual_app.dependency_overrides, get_extraction_service, lambda: service)
        try:
            async with lifespan(actual_app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=actual_app), base_url="http://test") as client:
                    extraction = asyncio.create_task(client.post("/api/extract", files=fields("[]")))
                    await asyncio.wait_for(started.wait(), timeout=2)
                    health = await asyncio.wait_for(client.get("/health"), timeout=0.5)
                    assert health.status_code == 200 and not extraction.done()
                    finish.set()
                    assert (await extraction).status_code == 200
        finally:
            finish.set()

    asyncio.run(run())


def test_slow_fragmented_upload_times_out_and_closes_temporary_file(monkeypatch):
    import starlette.formparsers

    created = []
    original = starlette.formparsers.SpooledTemporaryFile

    def tracked(*args, **kwargs):
        result = original(*args, **kwargs)
        created.append(result)
        return result

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", tracked)
    app, ocr, _ = make_app(monkeypatch, Settings(extract_upload_timeout_seconds=0.05))

    async def body():
        yield (b'--boundary\r\nContent-Disposition: form-data; name="pdf_file"; filename="x.pdf"\r\n'
               b'Content-Type: application/pdf\r\n\r\npartial')
        await asyncio.sleep(1)
        yield b"unreachable"

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/extract", content=body(), headers={"Content-Type": "multipart/form-data; boundary=boundary"})

    response = asyncio.run(run())
    assert response.status_code == 408 and ocr.calls == 0
    assert len(created) == 1 and created[0].closed


def test_cancelled_request_closes_the_parsed_upload(monkeypatch):
    import starlette.formparsers

    created = []
    original = starlette.formparsers.SpooledTemporaryFile

    def tracked(*args, **kwargs):
        result = original(*args, **kwargs)
        created.append(result)
        return result

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", tracked)

    async def run():
        started = asyncio.Event()

        class WaitingOCR(FakeOCR):
            async def extract_stream_async(self, stream):
                started.set()
                await asyncio.Event().wait()

        app, _, _ = make_app(monkeypatch, ocr=WaitingOCR())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            request = asyncio.create_task(client.post("/api/extract", files=fields("[]")))
            await asyncio.wait_for(started.wait(), timeout=2)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request

    asyncio.run(run())
    assert len(created) == 1 and created[0].closed


def test_unexpected_errors_do_not_expose_document_content(monkeypatch, caplog):
    app, _, _ = make_app(monkeypatch, ocr=FakeOCR(RuntimeError("private document")))
    with TestClient(app) as client:
        response = client.post("/api/extract", files=fields("[]"))
    assert response.status_code == 500
    assert "private document" not in response.text and "private document" not in caplog.text


@pytest.mark.parametrize("data", [b"", b"not a PDF", b"%PDF-1.4\ninvalid"])
def test_real_endpoint_rejects_invalid_pdf_contents(data):
    with TestClient(actual_app) as client:
        response = client.post("/api/extract", files=fields("[]", data))
    assert response.status_code == 400


def test_real_endpoint_rejects_password_protected_pdf():
    import pymupdf

    with pymupdf.open() as pdf:
        pdf.new_page()
        protected = pdf.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret")
    with TestClient(actual_app) as client:
        response = client.post("/api/extract", files=fields("[]", protected))
    assert response.status_code == 400 and "secret" not in response.text


def test_real_endpoint_coordinates_match_two_synthetic_scanned_pages():
    import pymupdf

    expected = []
    with pymupdf.open() as original, pymupdf.open() as scanned:
        for y in (80, 160):
            page = original.new_page(width=500, height=300)
            page.insert_text((100, y), "Alice Smith met Bob Jones in London.", fontsize=22)
            expected.append(page.search_for("Alice Smith")[0])
            pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            target = scanned.new_page(width=500, height=300)
            target.insert_image(target.rect, pixmap=pix)
        pdf = scanned.tobytes()
    names = json.dumps([{"first_name": "Alice", "last_name": "Smith"}])
    with TestClient(actual_app) as client:
        response = client.post("/api/extract", files=fields(names, pdf))
    assert response.status_code == 200, response.text
    found = [item for item in response.json()["extracted_names"] if item["name"] == "Alice Smith"]
    assert {item["bounding_box"]["page_number"] for item in found} == {0, 1}
    for item in found:
        box = item["bounding_box"]
        center = pymupdf.Point(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        assert center in expected[box["page_number"]]


def test_real_endpoint_coordinates_remain_crop_relative_on_rotated_page():
    import pymupdf

    with pymupdf.open() as original, pymupdf.open() as scanned:
        page = original.new_page(width=500, height=300)
        page.insert_text((100, 100), "Alice Smith met Bob Jones in London.", fontsize=22)
        expected = page.search_for("Alice Smith")[0] + (-50, -30, -50, -30)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        target = scanned.new_page(width=500, height=300)
        target.insert_image(target.rect, pixmap=pix)
        target.set_cropbox(pymupdf.Rect(50, 30, 450, 270))
        target.set_rotation(90)
        pdf = scanned.tobytes()
    names = json.dumps([{"first_name": "Alice", "last_name": "Smith"}])
    with TestClient(actual_app) as client:
        response = client.post("/api/extract", files=fields(names, pdf))
    assert response.status_code == 200, response.text
    found = [item for item in response.json()["extracted_names"] if item["name"] == "Alice Smith"]
    assert len(found) == 1
    box = found[0]["bounding_box"]
    center = pymupdf.Point(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    assert box["page_number"] == 0 and center in expected


def test_real_endpoint_ocr_ner_and_fuzzy_on_sample_pdf():
    sample_dir = Path(os.environ.get("SAMPLE_PDFS_DIR", Path(__file__).resolve().parents[2] / "sample_pdfs"))
    pdf = (sample_dir / "meeting_minutes.pdf").read_bytes()
    names = json.dumps([{"first_name": "Thomas", "last_name": "Muller"}])
    with TestClient(actual_app) as client:
        response = client.post("/api/extract", files=fields(names, pdf))
    assert response.status_code == 200, response.text
    result = response.json()
    assert {item["bounding_box"]["page_number"] for item in result["extracted_names"] if item["name"] == "Thomas Muller"} == {0, 1}
    assert any(match["matched_name"] == "Thomas Muller" and match["score"] == 1.0 for match in result["fuzzy_matches"])
    assert all(box["width"] > 0 and box["height"] > 0 for box in (item["bounding_box"] for item in result["extracted_names"]))
