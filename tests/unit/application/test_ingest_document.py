import logging
from collections.abc import Mapping, Sequence

import pytest

from app.application.ingest_document import IngestDocument
from app.domain.chunking import Chunk, document_id_for
from app.domain.document import Word
from app.domain.errors import VectorStoreUnavailable
from tests.fakes import (
    FakeEmbedder,
    FakeOcrEngine,
    FakeRasterizer,
    InMemoryVectorStore,
    line_of_words,
)

PDF = b"%PDF-1.7 two pages"
WORDS_BY_PAGE = {
    0: line_of_words(1, "Margaret Thompson approved the budget."),
    1: line_of_words(1, "Richard Hernandez adjourned the meeting."),
}


def _ingest(
    store: InMemoryVectorStore, words_by_page: Mapping[int, Sequence[Word]] = WORDS_BY_PAGE
) -> IngestDocument:
    return IngestDocument(
        rasterizer=FakeRasterizer(pages=2),
        ocr=FakeOcrEngine(words_by_page),
        embedder=FakeEmbedder(),
        store=store,
        dpi=300,
        max_tokens=250,
    )


def test_two_page_document_is_chunked_embedded_and_stored() -> None:
    store = InMemoryVectorStore()

    result = _ingest(store).execute(PDF, "minutes.pdf")

    doc_id = document_id_for(PDF)
    assert result.document_id == doc_id
    assert (result.page_count, result.chunk_count) == (2, 2)
    assert list(store.rows) == [f"{doc_id}:0", f"{doc_id}:1"]
    stored = [chunk for chunk, _ in store.rows.values()]
    assert stored == [
        Chunk(doc_id, "minutes.pdf", 0, 0, "Margaret Thompson approved the budget."),
        Chunk(doc_id, "minutes.pdf", 1, 1, "Richard Hernandez adjourned the meeting."),
    ]
    assert all(len(vector) == 26 for _, vector in store.rows.values())


def test_reingesting_the_same_pdf_replaces_its_chunks() -> None:
    store = InMemoryVectorStore()
    use_case = _ingest(store)

    use_case.execute(PDF, "minutes.pdf")
    result = use_case.execute(PDF, "minutes.pdf")

    assert result.chunk_count == 2
    assert len(store.rows) == 2


def test_a_different_pdf_never_overwrites_the_first() -> None:
    store = InMemoryVectorStore()
    use_case = _ingest(store)

    use_case.execute(PDF, "a.pdf")
    use_case.execute(b"%PDF-1.7 another document", "b.pdf")

    assert len(store.rows) == 4
    assert {chunk.file_name for chunk, _ in store.rows.values()} == {"a.pdf", "b.pdf"}


def test_document_without_text_stores_nothing_and_drops_stale_chunks() -> None:
    store = InMemoryVectorStore()
    stale = Chunk(document_id_for(PDF), "old.pdf", 0, 0, "stale text")
    store.replace_document(stale.document_id, [stale], [[1.0]])

    result = _ingest(store, words_by_page={}).execute(PDF, "blank.pdf")

    assert result.chunk_count == 0
    assert store.rows == {}


def test_missing_file_name_falls_back_to_the_document_id() -> None:
    store = InMemoryVectorStore()

    _ingest(store).execute(PDF, None)

    assert {chunk.file_name for chunk, _ in store.rows.values()} == {document_id_for(PDF)}


def test_store_failure_propagates() -> None:
    store = InMemoryVectorStore(error=VectorStoreUnavailable("down"))

    with pytest.raises(VectorStoreUnavailable):
        _ingest(store).execute(PDF, "minutes.pdf")


def test_completion_log_has_counts_but_no_text_or_file_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    _ingest(InMemoryVectorStore()).execute(PDF, "secret-minutes.pdf")

    records = [r for r in caplog.records if r.getMessage() == "ingest_completed"]
    assert len(records) == 1
    fields = records[0].__dict__
    assert fields["document_id"] == document_id_for(PDF)
    assert (fields["page_count"], fields["chunk_count"]) == (2, 2)
    dumped = repr(fields)
    assert "secret-minutes" not in dumped
    assert "Margaret" not in dumped
