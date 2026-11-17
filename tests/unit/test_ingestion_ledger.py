from concurrent.futures import ThreadPoolExecutor
import os
import multiprocessing
import sqlite3
from uuid import uuid4

import pytest

from app.services.ingestion_ledger import (
    IngestionLedger,
    LedgerFormatError,
    LedgerStateError,
    PageRecord,
)


@pytest.fixture
def ledger(tmp_path):
    result = IngestionLedger(tmp_path / "ledger" / "ingestions.sqlite3")
    result.initialize()
    return result


def create(ledger, *, content="a" * 64, ingestion_id=None, document_id=None):
    return ledger.create(
        ingestion_id=ingestion_id or str(uuid4()),
        document_id=document_id or str(uuid4()),
        content_sha256=content,
        processing_signature="b" * 64,
        collection="documents_model_v1",
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_revision="1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        chunk_tokens=128,
        overlap_tokens=32,
    )


def test_uninitialized_ledger_is_not_created_by_read(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(LedgerFormatError):
        IngestionLedger(path).get(str(uuid4()))
    assert not path.exists()


def test_initialization_refuses_an_unrelated_database(tmp_path):
    path = tmp_path / "existing.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE user_data (value TEXT)")
        connection.execute("INSERT INTO user_data VALUES ('keep')")
    path.chmod(0o600)
    with pytest.raises(LedgerFormatError):
        IngestionLedger(path).initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM user_data").fetchone() == ("keep",)
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)


def test_initialization_is_idempotent_and_enables_wal(ledger):
    ledger.initialize()
    with sqlite3.connect(ledger.path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_path_with_uri_special_characters_is_opened_without_creating_another_file(tmp_path):
    path = tmp_path / "folder #1" / "ledger ?1.sqlite3"
    path.parent.mkdir(mode=0o700)
    ledger = IngestionLedger(path)
    ledger.initialize()
    attempt = create(ledger)
    assert IngestionLedger(path).get(attempt.ingestion_id) == attempt


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
def test_invalid_sqlite_timeouts_are_rejected(tmp_path, timeout):
    with pytest.raises(ValueError):
        IngestionLedger(tmp_path / "ledger.sqlite3", timeout_seconds=timeout)


def test_page_records_preserve_empty_physical_pages_after_reopening(ledger):
    attempt = create(ledger)
    pages = [PageRecord(0, False, 0), PageRecord(1, True, 2), PageRecord(2, False, 0)]
    ledger.record_pages(attempt.ingestion_id, pages, physical_pages=3)
    reopened = IngestionLedger(ledger.path)
    reopened.initialize()
    assert reopened.pages(attempt.ingestion_id) == pages
    reopened.start_writing(attempt.ingestion_id)
    assert reopened.get(attempt.ingestion_id).expected_chunks == 2
    reopened.complete(attempt.ingestion_id)
    assert IngestionLedger(ledger.path).get(attempt.ingestion_id).state == "completed"


def test_same_content_creates_distinct_attempts_without_automatic_deduplication(ledger):
    first = create(ledger)
    second = create(ledger)
    assert first.ingestion_id != second.ingestion_id and first.document_id != second.document_id
    assert {item.ingestion_id for item in ledger.find_by_content("a" * 64)} == {
        first.ingestion_id, second.ingestion_id,
    }


@pytest.mark.parametrize("pages", [
    [],
    [PageRecord(1, True, 1)],
    [PageRecord(0, False, 1)],
    [PageRecord(0, True, -1)],
    [PageRecord(0, 1, 1)],
    [PageRecord(0, True, 1), PageRecord(0, True, 1)],
])
def test_invalid_or_incomplete_physical_page_sequences_are_rejected(ledger, pages):
    attempt = create(ledger)
    with pytest.raises(ValueError):
        ledger.record_pages(attempt.ingestion_id, pages, physical_pages=2)
    assert ledger.pages(attempt.ingestion_id) == []


def test_all_empty_pages_are_persisted_but_cannot_be_written(ledger):
    attempt = create(ledger)
    ledger.record_pages(attempt.ingestion_id, [PageRecord(0, False, 0), PageRecord(1, False, 0)], physical_pages=2)
    with pytest.raises(LedgerStateError):
        ledger.start_writing(attempt.ingestion_id)
    ledger.fail(attempt.ingestion_id, "no_text")
    assert ledger.get(attempt.ingestion_id).state == "failed"
    assert ledger.pages(attempt.ingestion_id) == [PageRecord(0, False, 0), PageRecord(1, False, 0)]


def test_started_write_failure_requires_cleanup_not_assumed_rollback(ledger):
    attempt = create(ledger)
    ledger.record_pages(attempt.ingestion_id, [PageRecord(0, True, 2)], physical_pages=1)
    ledger.start_writing(attempt.ingestion_id)
    ledger.fail(attempt.ingestion_id, "qdrant_timeout")
    result = ledger.get(attempt.ingestion_id)
    assert (result.state, result.error_code, result.expected_chunks) == ("cleanup_pending", "qdrant_timeout", 2)
    with pytest.raises(LedgerStateError):
        ledger.complete(attempt.ingestion_id)


def test_completed_attempt_cannot_be_failed_or_rewritten(ledger):
    attempt = create(ledger)
    ledger.record_pages(attempt.ingestion_id, [PageRecord(0, True, 1)], physical_pages=1)
    ledger.start_writing(attempt.ingestion_id)
    ledger.complete(attempt.ingestion_id)
    with pytest.raises(LedgerStateError):
        ledger.fail(attempt.ingestion_id, "internal_error")
    with pytest.raises(LedgerStateError):
        ledger.start_writing(attempt.ingestion_id)
    with pytest.raises(LedgerStateError):
        ledger.record_pages(attempt.ingestion_id, [PageRecord(0, True, 1)], physical_pages=1)


def test_record_pages_is_not_silently_replaced(ledger):
    attempt = create(ledger)
    ledger.record_pages(attempt.ingestion_id, [PageRecord(0, False, 0)], physical_pages=1)
    with pytest.raises(LedgerStateError):
        ledger.record_pages(attempt.ingestion_id, [PageRecord(0, True, 1)], physical_pages=1)
    assert ledger.pages(attempt.ingestion_id) == [PageRecord(0, False, 0)]


def test_duplicate_ids_are_rejected_even_when_content_can_repeat(ledger):
    first = create(ledger)
    with pytest.raises(LedgerStateError):
        create(ledger, ingestion_id=first.ingestion_id)
    with pytest.raises(LedgerStateError):
        create(ledger, document_id=first.document_id)


def test_error_codes_cannot_accidentally_contain_document_text(ledger):
    attempt = create(ledger)
    with pytest.raises(ValueError):
        ledger.fail(attempt.ingestion_id, "private document text")
    with pytest.raises(ValueError):
        ledger.fail(attempt.ingestion_id, "confidential")
    assert ledger.get(attempt.ingestion_id).state == "processing"


def test_concurrent_start_writing_has_only_one_winner(ledger):
    attempt = create(ledger)
    ledger.record_pages(attempt.ingestion_id, [PageRecord(0, True, 1)], physical_pages=1)

    def start():
        try:
            IngestionLedger(ledger.path).start_writing(attempt.ingestion_id)
            return "started"
        except LedgerStateError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: start(), range(2)))
    assert sorted(outcomes) == ["rejected", "started"]
    assert ledger.get(attempt.ingestion_id).state == "writing"


def test_empty_existing_file_is_not_initialized(tmp_path):
    path = tmp_path / "unknown.sqlite3"
    path.touch(mode=0o600)
    with pytest.raises(LedgerFormatError):
        IngestionLedger(path).initialize()
    assert path.stat().st_size == 0


def test_files_are_private_and_symlinks_are_refused(tmp_path):
    ledger = IngestionLedger(tmp_path / "private" / "ledger.sqlite3")
    ledger.initialize()
    assert ledger.path.stat().st_mode & 0o777 == 0o600
    assert ledger.path.parent.stat().st_mode & 0o777 == 0o700
    link = tmp_path / "link.sqlite3"
    link.symlink_to(ledger.path)
    from app.services.ingestion_ledger import LedgerError
    with pytest.raises(LedgerError):
        IngestionLedger(link).initialize()


def test_uncertain_write_cannot_complete(ledger):
    record = create(ledger)
    ledger.record_pages(record.ingestion_id, [PageRecord(0, True, 1)], physical_pages=1)
    ledger.start_writing(record.ingestion_id)
    ledger.write_intent(record.ingestion_id)
    with pytest.raises(LedgerStateError):
        ledger.complete(record.ingestion_id)
    ledger.write_confirmed(record.ingestion_id)
    ledger.complete(record.ingestion_id)


def test_page_total_cannot_hide_an_omitted_last_page(ledger):
    record = create(ledger)
    with pytest.raises(ValueError):
        ledger.record_pages(record.ingestion_id, [PageRecord(0, True, 1)], physical_pages=2)


def _initialize_process(path, barrier, results):
    barrier.wait()
    try:
        IngestionLedger(path).initialize()
        results.put("ok")
    except Exception as error:
        results.put(type(error).__name__)


def test_initialization_is_serialized_across_processes(tmp_path):
    context = multiprocessing.get_context("fork")
    for trial in range(5):
        path = tmp_path / f"private-{trial}" / "ledger.sqlite3"
        barrier, results = context.Barrier(4), context.Queue()
        processes = [context.Process(target=_initialize_process, args=(path, barrier, results)) for _ in range(4)]
        try:
            for process in processes: process.start()
            for process in processes:
                process.join(timeout=10)
                assert not process.is_alive() and process.exitcode == 0
            assert [results.get(timeout=2) for _ in processes] == ["ok"] * 4
        finally:
            for process in processes:
                if process.is_alive(): process.terminate()
                process.join()


def _crash_during_write(path, ingestion_id):
    ledger = IngestionLedger(path)
    with ledger.attempt_lock(ingestion_id):
        ledger.start_writing(ingestion_id)
        ledger.write_intent(ingestion_id)
        os._exit(17)


def test_crashed_process_releases_lock_but_retains_write_uncertainty(ledger):
    record = create(ledger)
    ledger.record_pages(record.ingestion_id, [PageRecord(0, True, 1)], physical_pages=1)
    context = multiprocessing.get_context("fork")
    process = context.Process(target=_crash_during_write, args=(ledger.path, record.ingestion_id))
    process.start()
    try:
        process.join(timeout=10)
        assert process.exitcode == 17
        with ledger.attempt_lock(record.ingestion_id):
            recovered = ledger.recover(record.ingestion_id)
            assert recovered.state == "cleanup_pending" and recovered.write_uncertain
    finally:
        if process.is_alive(): process.terminate()
        process.join()


def test_pending_inventory_lists_only_active_or_cleanup_states(ledger):
    processing = create(ledger)
    writing = create(ledger)
    ledger.record_pages(writing.ingestion_id, [PageRecord(0, True, 1)], physical_pages=1)
    ledger.start_writing(writing.ingestion_id)
    failed = create(ledger)
    ledger.fail(failed.ingestion_id, "invalid_pdf")
    assert {record.ingestion_id for record in ledger.pending()} == {processing.ingestion_id, writing.ingestion_id}
    assert len(ledger.pending(limit=1)) == 1
    with pytest.raises(ValueError):
        ledger.pending(limit=0)
