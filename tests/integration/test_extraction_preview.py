"""Optional preview API with simulated OCR/NER and real multipart routing."""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from pydantic import ValidationError

from app.api.dependencies import get_extraction_service
from app.api.extract import router as extract_router
from app.api.extraction_preview import router as preview_router
from app.core.config import Settings
from app.models.document import OCRDocument, OCRPage, OCRWord, WordBox
from app.models.extraction import PersonSpan
from app.services.extraction_preview import LatestExtractionPreview
from app.services.extraction_service import ExtractionService


TOKEN = "test-preview-token-" + "x" * 32
HEADERS = {"Authorization": "Bearer " + TOKEN}


class OCR:
    def __init__(self):
        self.calls = 0

    async def extract_stream_async(self, upload):
        self.calls += 1
        await upload.read()
        words = (
            OCRWord("Luisa", WordBox(10, 10, 20, 10), 0, 5, 1, 1, 1, 95),
            OCRWord("Cha", WordBox(35, 10, 20, 10), 6, 9, 1, 1, 1, 95),
            OCRWord("Luisa", WordBox(90, 10, 20, 10), 10, 15, 1, 1, 1, 95),
            OCRWord("Cha", WordBox(115, 10, 20, 10), 16, 19, 1, 1, 1, 95),
        )
        return OCRDocument((OCRPage(0, 300, 200, "Luisa Cha Luisa Cha", words),))


class NER:
    def __init__(self):
        self.calls = 0

    async def detect_pages(self, pages):
        self.calls += 1
        return [[PersonSpan("Luisa Cha", 0, 9)]]


def make_app(monkeypatch, *, level=1, preview=True):
    settings = Settings(extract_preview_enabled=preview, extract_preview_token=TOKEN,
                        ner_name_recovery_passes=level)
    store = LatestExtractionPreview(TOKEN) if preview else None
    ocr, ner = OCR(), NER()
    service = ExtractionService(ocr, ner, settings, preview_store=store)
    app = FastAPI()
    app.state.extraction_preview_store = store
    app.include_router(extract_router, prefix="/api")
    app.include_router(preview_router, prefix="/api")
    app.dependency_overrides[get_extraction_service] = lambda: service
    monkeypatch.setattr("app.api.extract.get_settings", lambda: settings)
    return app, store, ocr, ner


def post(client, data=b"pdf"):
    return client.post("/api/extract", files={"pdf_file": ("doc.pdf", data, "application/pdf"), "names": (None, "[]")})


def test_preview_defaults_off_and_requires_a_strong_configured_token():
    assert Settings().extract_preview_enabled is False
    for value in (None, "short", "a" * 31, "a" * 31 + " "):
        with pytest.raises(ValidationError) as error:
            Settings(extract_preview_enabled=True, extract_preview_token=value)
        if value:
            assert value not in str(error.value)
    settings = Settings(extract_preview_enabled=True, extract_preview_token=TOKEN)
    assert TOKEN not in repr(settings) and TOKEN not in str(settings.model_dump())


def test_disabled_preview_is_not_accessible(monkeypatch):
    app, _, _, _ = make_app(monkeypatch, preview=False)
    with TestClient(app) as client:
        assert post(client).status_code == 200
        assert client.get("/api/extract/preview", headers=HEADERS).status_code == 404


def test_authenticated_preview_preserves_stages_and_uses_one_ocr_and_ner(monkeypatch, caplog):
    app, store, ocr, ner = make_app(monkeypatch)
    with TestClient(app) as client:
        result = post(client)
        assert result.status_code == 200 and len(result.json()["extracted_names"]) == 2
        assert client.get("/api/extract/preview").status_code == 401
        assert client.get("/api/extract/preview", headers={"Authorization": "Bearer wrong"}).status_code == 401
        info = client.get("/api/extract/preview", headers=HEADERS)
        assert info.status_code == 200 and info.headers["cache-control"].startswith("no-store")
        payload = info.json()
        assert payload["stages"] == ["ocr", "ner", "recovery_1", "final"]
        prefix = "/api/extract/preview/" + payload["preview_id"]
        document = client.get(prefix + "/document", headers=HEADERS)
        assert document.content == b"pdf" and document.headers["content-type"] == "application/pdf"
        assert document.headers["cache-control"].startswith("no-store")
        ocr_stage = client.get(prefix + "/stages/ocr", headers=HEADERS).json()
        ner_stage = client.get(prefix + "/stages/ner", headers=HEADERS).json()
        recovery = client.get(prefix + "/stages/recovery_1", headers=HEADERS).json()
        final = client.get(prefix + "/stages/final", headers=HEADERS).json()
        assert len(ocr_stage["pages"][0]["boxes"]) == 4
        assert len(ner_stage["pages"][0]["boxes"]) == 1
        assert [box["source"] for box in recovery["pages"][0]["boxes"]] == ["ner", "recovery_1"]
        assert final["extracted_names"] == result.json()["extracted_names"]
        assert client.get(prefix + "/stages/ocr").status_code == 401
        assert client.get(prefix + "/stages/nope", headers=HEADERS).status_code == 404
    assert ocr.calls == ner.calls == 1
    assert TOKEN not in caplog.text and "Luisa" not in caplog.text
    store.close()


def test_new_extraction_invalidates_previous_preview_identifier(monkeypatch):
    app, store, _, _ = make_app(monkeypatch)
    with TestClient(app) as client:
        assert post(client, b"first").status_code == 200
        first = client.get("/api/extract/preview", headers=HEADERS).json()["preview_id"]
        assert post(client, b"second").status_code == 200
        second = client.get("/api/extract/preview", headers=HEADERS).json()["preview_id"]
        assert first != second
        assert client.get(f"/api/extract/preview/{first}/document", headers=HEADERS).status_code == 404
        assert client.get(f"/api/extract/preview/{second}/document", headers=HEADERS).content == b"second"
    store.close()


def test_failed_new_extraction_clears_the_previous_preview(monkeypatch):
    from app.services.ocr_service import InvalidPDFError

    app, store, _, _ = make_app(monkeypatch)
    service = app.dependency_overrides[get_extraction_service]()
    original = service.ocr.extract_stream_async

    async def fail_invalid(upload):
        if await upload.read() == b"invalid":
            raise InvalidPDFError("private text")
        await upload.seek(0)
        return await original(upload)

    service.ocr.extract_stream_async = fail_invalid
    app.dependency_overrides[get_extraction_service] = lambda: service
    with TestClient(app) as client:
        assert post(client, b"first").status_code == 200
        old_id = client.get("/api/extract/preview", headers=HEADERS).json()["preview_id"]
        assert post(client, b"invalid").status_code == 400
        assert client.get("/api/extract/preview", headers=HEADERS).status_code == 404
        assert client.get(f"/api/extract/preview/{old_id}/document", headers=HEADERS).status_code == 404
    store.close()


def test_concurrent_older_extraction_cannot_replace_newer_preview(monkeypatch):
    async def run():
        app, store, _, ner = make_app(monkeypatch)
        started, release = asyncio.Event(), asyncio.Event()

        class RacingOCR(OCR):
            async def extract_stream_async(self, upload):
                data = await upload.read()
                if data == b"first":
                    started.set()
                    await release.wait()
                await upload.seek(0)
                return await super().extract_stream_async(upload)

        service = ExtractionService(RacingOCR(), ner, Settings(
            extract_preview_enabled=True, extract_preview_token=TOKEN, ner_name_recovery_passes=1,
        ), preview_store=store)
        app.dependency_overrides[get_extraction_service] = lambda: service
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = asyncio.create_task(client.post("/api/extract", files={
                "pdf_file": ("one.pdf", b"first"), "names": (None, "[]"),
            }))
            try:
                await asyncio.wait_for(started.wait(), 2)
                second = await client.post("/api/extract", files={
                    "pdf_file": ("two.pdf", b"second"), "names": (None, "[]"),
                })
                assert second.status_code == 200
                latest = (await client.get("/api/extract/preview", headers=HEADERS)).json()["preview_id"]
                release.set()
                assert (await first).status_code == 200
                assert (await client.get("/api/extract/preview", headers=HEADERS)).json()["preview_id"] == latest
                assert (await client.get(f"/api/extract/preview/{latest}/document", headers=HEADERS)).content == b"second"
            finally:
                release.set()
                await first
                store.close()
    asyncio.run(run())


def test_over_limit_preview_does_not_fail_extraction_or_leave_previous_document(monkeypatch):
    app, store, _, _ = make_app(monkeypatch)
    with TestClient(app) as client:
        assert post(client).status_code == 200
        assert client.get("/api/extract/preview", headers=HEADERS).status_code == 200
        monkeypatch.setattr("app.services.extraction_service.MAX_PREVIEW_PDF_BYTES", 2)
        assert post(client, b"larger").status_code == 200
        assert client.get("/api/extract/preview", headers=HEADERS).status_code == 404
    store.close()


def test_preview_word_limit_leaves_extraction_response_unchanged(monkeypatch):
    app, store, _, _ = make_app(monkeypatch)
    monkeypatch.setattr("app.services.extraction_preview.MAX_PREVIEW_WORDS", 3)
    with TestClient(app) as client:
        result = post(client)
        assert result.status_code == 200 and len(result.json()["extracted_names"]) == 2
        assert client.get("/api/extract/preview", headers=HEADERS).status_code == 404
    store.close()


def test_preview_read_failure_does_not_break_extraction_or_log_contents(caplog):
    class BrokenPreviewStream:
        async def seek(self, offset):
            raise RuntimeError("private file contents")

        async def read(self, size=-1):
            return b"pdf"

    class OCRIgnoringStream(OCR):
        async def extract_stream_async(self, upload):
            return await super().extract_stream_async(BrokenPreviewStream())

    async def run():
        store = LatestExtractionPreview(TOKEN)
        service = ExtractionService(OCRIgnoringStream(), NER(), Settings(
            extract_preview_enabled=True, extract_preview_token=TOKEN, ner_name_recovery_passes=1,
        ), preview_store=store)
        result = await service.extract(BrokenPreviewStream(), [])
        assert len(result.extracted_names) == 2 and store.get() is None
        store.close()

    asyncio.run(run())
    assert "private file contents" not in caplog.text


def test_preview_publication_failure_does_not_break_extraction(monkeypatch, caplog):
    app, store, _, _ = make_app(monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError("private preview contents")

    monkeypatch.setattr(store, "publish", fail)
    with TestClient(app) as client:
        result = post(client)
        assert result.status_code == 200 and len(result.json()["extracted_names"]) == 2
        assert client.get("/api/extract/preview", headers=HEADERS).status_code == 404
    assert "private preview contents" not in caplog.text
    store.close()


@pytest.mark.parametrize("level,expected", [
    (0, ["ocr", "ner", "final"]),
    (3, ["ocr", "ner", "recovery_1", "recovery_2", "recovery_3", "final"]),
])
def test_preview_lists_only_the_enabled_processing_stages(monkeypatch, level, expected):
    app, store, _, _ = make_app(monkeypatch, level=level)
    with TestClient(app) as client:
        assert post(client).status_code == 200
        assert client.get("/api/extract/preview", headers=HEADERS).json()["stages"] == expected
    store.close()


def test_preview_store_expiration_and_generation_prevent_stale_publication():
    async def run():
        store = LatestExtractionPreview(TOKEN, ttl_seconds=0.03)
        old = store.begin()
        current = store.begin()
        assert not store.publish(old, b"old", {"ocr": b"{}"})
        assert store.publish(current, b"new", {"ocr": b"{}"})
        preview_id = store.get().preview_id
        assert store.get(preview_id).pdf == b"new"
        await asyncio.sleep(0.06)
        assert store._preview is None and store.get() is None
        pending = store.begin()
        store.close()
        assert not store.publish(pending, b"old", {"ocr": b"{}"})
        assert not store.is_current(store.begin())
    asyncio.run(run())
