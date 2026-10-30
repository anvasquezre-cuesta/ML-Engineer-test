import hashlib
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_chunk_store, get_embedder, get_ocr_engine
from app.main import app
from app.services.rag_service import chunk_text
from app.services.vector_service import VectorStoreError, _collection
from tests.unit.test_ocr_service import FakeEngine, blank_pdf, row
from tests.unit.test_vector_service import FakeEmbedder

SENTENCE = (
    "Richard Hernandez called the meeting to order. Jennifer Liu confirmed quorum."
)
WORDS = [row(w, left=10 * i) for i, w in enumerate(SENTENCE.split())]


@pytest.fixture
def client(chroma, monkeypatch):
    """App with a fake OCR engine and embedder; 72 dpi means scale 1."""
    monkeypatch.setenv("OCR_DPI", "72")
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    monkeypatch.setenv("CHUNK_SIZE", "50")
    monkeypatch.setenv("CHUNK_OVERLAP", "20")
    embedder = FakeEmbedder()
    app.dependency_overrides[get_ocr_engine] = lambda: FakeEngine(*WORDS)
    app.dependency_overrides[get_embedder] = lambda: embedder
    yield TestClient(app), embedder
    app.dependency_overrides.clear()


def post(client, pdf: bytes, filename: str = "doc.pdf"):
    return client.post(
        "/api/ingest", files={"pdf_file": (filename, pdf, "application/pdf")}
    )


def test_ac_ing_01_ingests_two_pages_with_sha256_ids(client, caplog):
    http, _ = client
    caplog.set_level(logging.INFO, logger="app")
    pdf = blank_pdf(2)

    response = post(http, pdf, "secret_report.pdf")

    n_chunks = 2 * len(chunk_text(SENTENCE, 50, 20))
    assert response.status_code == 200
    assert response.json() == {"status": "ingested", "chunks_stored": n_chunks}
    sha = hashlib.sha256(pdf).hexdigest()
    expected = {f"{sha}:{p}:{c}" for p in (0, 1) for c in (0, 1)}
    stored = _collection().get()
    assert set(stored["ids"]) == expected
    assert sorted(stored["documents"]) == sorted(2 * chunk_text(SENTENCE, 50, 20))
    assert {m["filename"] for m in stored["metadatas"]} == {"secret_report.pdf"}
    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "app"]
    assert any(e.get("pages") == 2 and e.get("chunks") == n_chunks for e in events)
    assert "secret_report" not in caplog.text


def test_ac_ing_02_blank_pdf_stores_nothing(client):
    http, embedder = client
    post(http, blank_pdf(1))
    stored, calls = _collection().count(), embedder.calls
    app.dependency_overrides[get_ocr_engine] = lambda: FakeEngine()

    response = post(http, blank_pdf(2))

    assert response.status_code == 200
    assert response.json()["chunks_stored"] == 0
    assert _collection().count() == stored
    assert embedder.calls == calls


@pytest.mark.parametrize(
    ("data", "status"),
    [(b"not a pdf", 422), (b"0" * (1024 * 1024 + 1), 413)],
    ids=["not-a-pdf", "too-large"],
)
def test_ac_ing_03_invalid_upload_never_embeds(client, data, status):
    http, embedder = client

    response = post(http, data)

    assert response.status_code == status
    assert "detail" in response.json()
    assert embedder.calls == 0


def test_ac_ing_03_vector_store_down_is_503(client):
    http, _ = client

    def down(*args, **kwargs):
        raise VectorStoreError("down")

    app.dependency_overrides[get_chunk_store] = lambda: down

    response = post(http, blank_pdf())

    assert response.status_code == 503
    assert response.json() == {"detail": "down"}


def test_ac_vec_di_01_ingest_uses_injected_store(client):
    http, _ = client
    received = []
    app.dependency_overrides[get_chunk_store] = lambda: (
        lambda *args: received.append(args)
    )

    response = post(http, blank_pdf(1), "doc.pdf")

    chunks, metadata, _ = received[0]
    assert response.status_code == 200
    assert chunks == chunk_text(SENTENCE, 50, 20)
    assert [m["chunk"] for m in metadata] == [0, 1]
    assert {m["filename"] for m in metadata} == {"doc.pdf"}
    assert _collection().count() == 0
