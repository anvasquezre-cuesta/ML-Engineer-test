"""Real OCR, pinned local embeddings, chunking and SQLite; no Qdrant or HTTP."""

import hashlib
import math
import os
from uuid import uuid4

import pymupdf
import pytest

from app.core.embedding_model import MODEL_DIRECTORY, MODEL_NAME, MODEL_REVISION
from app.services.chunking_service import TokenAwareChunker
from app.services.embedding_service import EmbeddingInputError, EmbeddingModel
from app.services.ingestion_ledger import IngestionLedger, PageRecord
from app.services.ocr_service import OCRService


@pytest.fixture(scope="module")
def model():
    result = EmbeddingModel(os.environ.get("EMBEDDING_MODEL_DIR", MODEL_DIRECTORY))
    yield result
    result.close()


def test_real_model_runs_locally_and_rejects_truncation(model):
    chunker = TokenAwareChunker(model.tokenizer, max_tokens=128, overlap_tokens=32, model_max_tokens=256)
    text = " ".join(["The board reviewed the annual budget."] * 70)
    chunks = chunker.split_page(text, 1)
    assert len(chunks) > 1 and all(chunk.page_number == 1 and chunk.token_count <= 128 for chunk in chunks)
    vectors = model.encode([chunks[0].text, chunks[0].text])
    assert len(vectors) == 2 and all(len(vector) == 384 for vector in vectors)
    assert all(math.isfinite(value) for vector in vectors for value in vector)
    assert sum(left * right for left, right in zip(*vectors)) > 0.999
    with pytest.raises(EmbeddingInputError):
        model.encode([text])


def test_real_ocr_preserves_empty_first_page_in_sqlite_without_embedding_it(model, tmp_path):
    with pymupdf.open() as original, pymupdf.open() as scanned:
        page = original.new_page(width=600, height=300)
        page.insert_text((70, 120), "The board reviewed the annual budget on Monday.", fontsize=24)
        pixels = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        scanned.new_page(width=600, height=300)
        second = scanned.new_page(width=600, height=300)
        second.insert_image(second.rect, pixmap=pixels)
        pdf = scanned.tobytes()

    document = OCRService().extract(pdf)
    assert [page.page_number for page in document.pages] == [0, 1]
    assert not document.pages[0].text.strip()
    assert "budget" in document.pages[1].text.casefold()

    chunker = TokenAwareChunker(model.tokenizer, max_tokens=128, overlap_tokens=32, model_max_tokens=256)
    chunks_by_page = [chunker.split_page(page.text, page.page_number) for page in document.pages]
    assert not chunks_by_page[0] and chunks_by_page[1]
    vectors = model.encode([chunk.text for chunks in chunks_by_page for chunk in chunks])
    assert len(vectors) == sum(map(len, chunks_by_page))

    ledger = IngestionLedger(tmp_path / "ingestion.sqlite3")
    ledger.initialize()
    attempt = ledger.create(
        ingestion_id=str(uuid4()), document_id=str(uuid4()),
        content_sha256=hashlib.sha256(pdf).hexdigest(),
        processing_signature=hashlib.sha256(b"integration-test-recipe").hexdigest(),
        collection="isolated_test", model_name=MODEL_NAME, model_revision=MODEL_REVISION,
        chunk_tokens=128, overlap_tokens=32,
    )
    ledger.record_pages(attempt.ingestion_id, [
        PageRecord(page.page_number, bool(page.text.strip()), len(chunks))
        for page, chunks in zip(document.pages, chunks_by_page, strict=True)
    ], physical_pages=len(document.pages))
    assert IngestionLedger(ledger.path).pages(attempt.ingestion_id) == [
        PageRecord(0, False, 0), PageRecord(1, True, len(chunks_by_page[1])),
    ]
    assert ledger.get(attempt.ingestion_id).state == "processing"


def test_real_unknown_tokens_preserve_original_text_and_do_not_reject_document(model):
    chunker = TokenAwareChunker(model.tokenizer)
    text = "A report 📄 is ready. " + "a" * 110
    assert model.tokenizer.unk_token_id in model.tokenizer.encode(text, add_special_tokens=True, truncation=False)
    chunks = chunker.split_page(text, 0)
    assert len(chunks) == 1 and chunks[0].text == text
    assert len(model.encode([chunks[0].text])[0]) == 384


def test_real_worker_reuses_model_and_can_be_closed():
    import asyncio
    from app.core.config import Settings
    from app.services.embedding_async import EmbeddingService
    async def run():
        service = EmbeddingService(Settings())
        try:
            first = await service.prepare(["", "The board reviewed the annual budget."])
            process = service._process
            second = await service.prepare(["Alice Smith attended the meeting."])
            assert service._process is process and len(first.vectors) == len(first.chunks) == 1
            assert first.pages == [PageRecord(0, False, 0), PageRecord(1, True, 1)]
            assert len(second.vectors[0]) == 384
        finally:
            await service.aclose()
        assert process.returncode is not None
    asyncio.run(run())


def test_real_worker_embeds_query_without_truncation_and_reuses_ingestion_worker():
    import asyncio
    from app.core.config import Settings
    from app.services.embedding_async import EmbeddingService
    from app.services.embedding_service import EmbeddingInputError

    async def run():
        service = EmbeddingService(Settings(embedding_query_max_tokens=16))
        try:
            prepared = await service.prepare(["The board reviewed the annual budget."])
            process = service._process
            vector = await service.embed_query("  The board reviewed the annual budget.  ")
            assert service._process is process and len(vector) == 384
            assert sum(a * b for a, b in zip(vector, prepared.vectors[0], strict=True)) > 0.999
            assert all(math.isfinite(value) for value in vector)
            with pytest.raises(EmbeddingInputError):
                await service.embed_query("budget " * 40)
            assert service._process is None
        finally:
            await service.aclose()
        assert process.returncode is not None
    asyncio.run(run())
