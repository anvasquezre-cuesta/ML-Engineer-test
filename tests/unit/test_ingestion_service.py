import pytest
from structlog.testing import capture_logs

from app.domain.errors import UnsupportedMediaType
from app.domain.models import OcrWord
from app.services.chunking import WordWindowChunker
from app.services.documents import DocumentLoader, document_id
from app.services.ingestion import IngestionService
from app.services.ocr import OcrService
from tests.fakes import (
    FakeEmbedder,
    FakeOCR,
    FakeRenderer,
    InMemoryVectorStore,
    blank_page,
    ocr_word,
)


def _words(text: str) -> list[OcrWord]:
    return [ocr_word(w, 10 * i, 0, 10 * i + 8, 10) for i, w in enumerate(text.split())]


def _service(
    ocr: FakeOCR, pages: int = 2, chunk_words: int = 4, overlap: int = 1
) -> tuple[IngestionService, FakeEmbedder, InMemoryVectorStore]:
    renderer = FakeRenderer([blank_page(i) for i in range(pages)])
    embedder, store = FakeEmbedder(), InMemoryVectorStore()
    service = IngestionService(
        DocumentLoader(renderer, max_bytes=10_000, max_pages=10),
        OcrService(renderer, ocr, dpi=72),
        WordWindowChunker(chunk_words, overlap),
        embedder,
        store,
    )
    return service, embedder, store


def test_chunks_are_per_page_with_page_and_index_in_the_id() -> None:
    ocr = FakeOCR({0: _words("a b c d e f g"), 1: _words("h i")})
    service, _, store = _service(ocr)

    result = service.ingest(b"%PDF-doc", "memo.pdf")

    doc = document_id(b"%PDF-doc")
    assert result.chunks_stored == 3
    assert sorted(store.rows) == [f"{doc}:0:0", f"{doc}:0:1", f"{doc}:1:0"]
    assert [store.rows[f"{doc}:0:{i}"][0].text for i in (0, 1)] == ["a b c d", "d e f g"]
    assert {c.filename for c, _ in store.rows.values()} == {"memo.pdf"}


def test_all_chunks_are_embedded_in_one_batch() -> None:
    service, embedder, _ = _service(FakeOCR({0: _words("a b c d e"), 1: _words("f g")}))

    service.ingest(b"%PDF-doc", "memo.pdf")

    assert embedder.calls == [["a b c d", "d e", "f g"]]


def test_second_ingest_does_not_overwrite_first() -> None:
    service, _, store = _service(FakeOCR({0: _words("a b c"), 1: _words("d e")}))

    service.ingest(b"%PDF-first", "first.pdf")
    service.ingest(b"%PDF-second", "second.pdf")

    assert store.count() == 4  # two pages each, from two documents
    assert {c.filename for c, _ in store.rows.values()} == {"first.pdf", "second.pdf"}


def test_reingesting_the_same_file_changes_nothing() -> None:
    service, _, store = _service(FakeOCR({0: _words("a b c"), 1: _words("d e")}))

    service.ingest(b"%PDF-same", "a.pdf")
    before = dict(store.rows)
    service.ingest(b"%PDF-same", "a.pdf")

    assert store.rows.keys() == before.keys()


def test_pages_without_text_produce_no_chunks() -> None:
    service, _, store = _service(FakeOCR({0: [], 1: _words("only page two")}))

    result = service.ingest(b"%PDF-doc", "memo.pdf")

    assert result.chunks_stored == 1
    assert [c.page for c, _ in store.rows.values()] == [1]


def test_document_without_any_text_logs_a_warning() -> None:
    service, _, _ = _service(FakeOCR())

    with capture_logs() as logs:
        result = service.ingest(b"%PDF-blank", "blank.pdf")

    assert result.chunks_stored == 0
    assert any(e["event"] == "ingest_no_text" for e in logs)


def test_invalid_upload_stops_before_ocr() -> None:
    ocr = FakeOCR()
    service, embedder, _ = _service(ocr)

    with pytest.raises(UnsupportedMediaType):
        service.ingest(b"PK\x03\x04 zip", "x.pdf")
    assert ocr.seen_pages == []
    assert embedder.calls == []
