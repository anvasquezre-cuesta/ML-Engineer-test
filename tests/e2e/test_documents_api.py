"""Ingest and document endpoints over HTTP, on an in-memory Qdrant."""

import hashlib

from fastapi import testclient
import pytest

from tests.e2e import wiring

pytestmark = pytest.mark.e2e

PDF = b"%PDF-1.7\nminutes"


def ingest(client: testclient.TestClient, filename: str) -> dict[str, object]:
    """Uploads ``PDF`` under ``filename`` to the ingest endpoint.

    Args:
        client: The test client.
        filename: Name of the uploaded file, used as the document key.

    Returns:
        The HTTP status and the decoded body.
    """
    response = client.post(
        "/api/ingest", files={"pdf_file": (filename, PDF, "application/pdf")}
    )
    return {"http_status": response.status_code, **response.json()}


def test_ingested_document_is_listed_by_filename_until_deleted() -> None:
    with wiring.fake_client(raise_server_exceptions=True) as client:
        stored = ingest(client, "minutes.pdf")
        listed = client.get("/api/documents").json()
        deleted = client.delete("/api/documents/minutes.pdf").json()
        missing = client.get("/api/documents/minutes.pdf")
        remaining = client.get("/api/documents").json()

    chunks = stored["chunks_stored"]
    assert stored == {
        "http_status": 200,
        "status": "ingested",
        "chunks_stored": chunks,
    }
    assert isinstance(chunks, int) and chunks > 0
    assert listed == [
        {
            "document_key": "minutes.pdf",
            "content_hash": hashlib.sha256(PDF).hexdigest(),
            "chunk_count": chunks,
        }
    ]
    assert deleted == {"document_key": "minutes.pdf", "chunks_deleted": chunks}
    assert (missing.status_code, missing.json()["code"]) == (
        404,
        "document.not_found",
    )
    assert remaining == []
