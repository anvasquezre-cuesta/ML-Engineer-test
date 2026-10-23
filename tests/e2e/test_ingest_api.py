"""``POST /api/ingest`` through HTTP with fake adapters."""

from typing import Any

import httpx
import pytest

from app.api.rag import safe_filename
from tests.e2e.conftest import PDF, ClientFactory
from tests.fakes import InMemoryVectorStore


def _ingest(client: Any, pdf: bytes = PDF, filename: str = "memo.pdf") -> httpx.Response:
    response: httpx.Response = client.post(
        "/api/ingest", files={"pdf_file": (filename, pdf, "application/pdf")}
    )
    return response


def test_ingest_returns_status_and_chunk_count(make_client: ClientFactory) -> None:
    response = _ingest(make_client())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "chunks_stored": 1}


def test_second_document_does_not_overwrite_the_first(make_client: ClientFactory) -> None:
    store = InMemoryVectorStore()
    client = make_client(store=store)

    _ingest(client, pdf=PDF, filename="first.pdf")
    _ingest(client, pdf=PDF + b" second", filename="second.pdf")
    _ingest(client, pdf=PDF, filename="first.pdf")  # same bytes again: idempotent

    assert store.count() == 2
    assert {c.filename for c, _ in store.rows.values()} == {"first.pdf", "second.pdf"}


@pytest.mark.parametrize(
    ("pdf", "status"),
    [(b"\x89PNG\r\n\x1a\n....", 415), (b"", 422), (b"%PDF-" + b"x" * 2000, 413)],
)
def test_rejections(make_client: ClientFactory, pdf: bytes, status: int) -> None:
    response = _ingest(make_client(max_upload_bytes=1000), pdf=pdf)

    assert response.status_code == status
    assert "request_id" in response.json()


@pytest.mark.parametrize(
    ("raw", "safe"),
    [
        ("memo.pdf", "memo.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\scan.pdf", "scan.pdf"),
        ("", "document.pdf"),
        (None, "document.pdf"),
        ("a" * 300, "a" * 255),
    ],
)
def test_safe_filename(raw: str | None, safe: str) -> None:
    assert safe_filename(raw) == safe
