"""T-007: every upload / names rejection, in order, before any OCR work."""

import io
import json
import logging
import tempfile
from collections.abc import Callable
from pathlib import Path

import pymupdf
import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from httpx import Response

from app.api.dependencies import Container
from app.api.upload import UploadLimits, read_pdf_upload
from app.domain.errors import UploadTooLarge
from app.infrastructure.pymupdf_rasterizer import PyMuPdfRasterizer
from app.infrastructure.settings import Settings
from app.main import create_app
from tests.fakes import FakeOcrEngine, FakeRasterizer
from tests.unit.api.conftest import fake_container

MAX_BYTES = 8 * 1024
MAX_PAGES = 2


def _pdf(pages: int = 1, encrypted: bool = False) -> bytes:
    with pymupdf.open() as doc:
        for _ in range(pages):
            doc.new_page()
        if encrypted:
            return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
        return doc.tobytes()


@pytest.fixture
def ocr() -> FakeOcrEngine:
    return FakeOcrEngine()


@pytest.fixture
def client(make_client: Callable[..., TestClient], ocr: FakeOcrEngine) -> TestClient:
    settings = Settings(_env_file=None, max_upload_bytes=MAX_BYTES, max_pages=MAX_PAGES)

    def build(s: Settings) -> Container:
        return fake_container(s, rasterizer=PyMuPdfRasterizer(), ocr=ocr)

    return make_client(create_app(settings, build_container=build))


def _post(
    client: TestClient,
    content: bytes,
    filename: str = "doc.pdf",
    content_type: str = "application/pdf",
    names: str = "[]",
) -> Response:
    return client.post(
        "/api/extract",
        files={"pdf_file": (filename, content, content_type)},
        data={"names": names},
    )


def _assert_error(response: Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert error["request_id"]


def test_content_not_extension_decides(client: TestClient, ocr: FakeOcrEngine) -> None:
    _assert_error(
        _post(client, b"just some notes, not a PDF", "fake.pdf", "application/pdf"),
        415,
        "upload_not_pdf",
    )
    _assert_error(
        _post(client, b"# README\n\nMarkdown text", "README.md", "application/pdf"),
        415,
        "upload_not_pdf",
    )
    assert _post(client, _pdf(), "scan.txt", "text/plain").status_code == 200
    assert ocr.calls == [0]


def test_empty_and_oversized_are_rejected_before_ocr(
    client: TestClient, ocr: FakeOcrEngine
) -> None:
    _assert_error(_post(client, b""), 400, "upload_empty")
    too_large = _post(client, b"%PDF-" + b"0" * MAX_BYTES)
    _assert_error(too_large, 413, "upload_too_large")
    assert str(MAX_BYTES) in too_large.json()["error"]["message"]
    assert ocr.calls == []


def test_unusable_pdfs_are_rejected_before_ocr(client: TestClient, ocr: FakeOcrEngine) -> None:
    _assert_error(_post(client, _pdf(encrypted=True)), 422, "pdf_encrypted")
    _assert_error(_post(client, b"%PDF-1.7 broken"), 422, "pdf_unreadable")
    _assert_error(_post(client, _pdf(pages=MAX_PAGES + 1)), 413, "pdf_too_many_pages")
    assert ocr.calls == []


@pytest.mark.parametrize(
    "names",
    [
        "not json",
        '{"first_name": "A"}',
        '[{"first_name": "Ana"}]',
        '[{"first_name": "", "last_name": "Lopez"}]',
        '[{"first_name": "  ", "last_name": "Lopez"}]',
    ],
)
def test_malformed_name_lists_are_rejected(client: TestClient, names: str) -> None:
    _assert_error(_post(client, _pdf(), names=names), 422, "names_invalid")


def test_names_error_names_the_failing_field(client: TestClient) -> None:
    response = _post(client, _pdf(), names=json.dumps([{"first_name": "Ana"}]))

    assert "names[0].last_name" in response.json()["error"]["message"]


def test_file_checks_run_before_names(client: TestClient) -> None:
    _assert_error(_post(client, b"", names="not json"), 400, "upload_empty")


def test_rejection_is_logged_with_code_and_size(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    _post(client, b"not a pdf at all")

    (record,) = [r for r in caplog.records if r.getMessage() == "upload_rejected"]
    assert vars(record)["code"] == "upload_not_pdf"
    assert vars(record)["size_bytes"] == len(b"not a pdf at all")


def test_no_temp_files_are_left_behind(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    spooled_to_disk = b"%PDF-" + b"0" * (2 * 1024 * 1024)  # above Starlette's 1 MB spool limit

    accepted = _post(client, _pdf())
    rejected = _post(client, spooled_to_disk)

    assert accepted.status_code == 200
    assert rejected.status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_size_message_names_the_limit_in_megabytes() -> None:
    limit = 20 * 1024 * 1024
    upload = UploadFile(io.BytesIO(b"%PDF-" + b"0" * limit))

    with pytest.raises(UploadTooLarge, match=r"20971520 bytes \(20 MB\)"):
        read_pdf_upload(upload, UploadLimits(limit, MAX_PAGES), FakeRasterizer(1))
