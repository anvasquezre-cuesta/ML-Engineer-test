import asyncio

import pytest

from app.core.config import Settings
from app.core.embedding_model import MODEL_NAME, MODEL_REVISION
from app.maintenance.cleanup_ingest import clean_attempt
from app.services.ingestion_ledger import IngestionLedger, LedgerFormatError, LedgerStateError, PageRecord
from app.services.ingestion_vectors import endpoint_key
from uuid import uuid4


class Store:
    lock_name = "collection-cleanup"
    def __init__(self): self.deleted = []
    async def ensure(self, **kwargs): assert kwargs == {"create": False}
    async def count(self, record): return 1
    async def clear_points(self, record): self.deleted.append(record.ingestion_id)


def setup_attempt(tmp_path, *, uncertain=False):
    settings = Settings(ingestion_ledger_path=str(tmp_path / "private" / "ledger.sqlite3"))
    ledger = IngestionLedger(settings.ingestion_ledger_path)
    ledger.initialize()
    record = ledger.create(
        ingestion_id=str(uuid4()), document_id=str(uuid4()), content_sha256="a" * 64,
        processing_signature="b" * 64, collection=settings.ingest_collection, model_name=MODEL_NAME,
        model_revision=MODEL_REVISION, chunk_tokens=128, overlap_tokens=32, endpoint_key=endpoint_key(settings.qdrant_url),
    )
    ledger.record_pages(record.ingestion_id, [PageRecord(0, True, 1)], physical_pages=1)
    ledger.start_writing(record.ingestion_id)
    if uncertain: ledger.write_intent(record.ingestion_id)
    return settings, ledger, record


def test_dry_run_does_not_change_state_or_delete(tmp_path):
    settings, ledger, record = setup_attempt(tmp_path)
    store = Store()
    result = asyncio.run(clean_attempt(settings, ledger, record.ingestion_id, store=store))
    assert result["action"] == "preview" and not store.deleted
    assert ledger.get(record.ingestion_id).state == "writing"


def test_active_lock_blocks_cleanup_even_with_confirmation(tmp_path):
    settings, ledger, record = setup_attempt(tmp_path)
    store = Store()
    with ledger.attempt_lock(record.ingestion_id), pytest.raises(LedgerStateError):
        asyncio.run(clean_attempt(settings, ledger, record.ingestion_id, store=store, execute=True, confirm_quiescent=True))
    assert not store.deleted


def test_uncertain_write_requires_operator_confirmation(tmp_path):
    settings, ledger, record = setup_attempt(tmp_path, uncertain=True)
    store = Store()
    with pytest.raises(LedgerStateError, match="Unknown write"):
        asyncio.run(clean_attempt(settings, ledger, record.ingestion_id, store=store, execute=True))
    assert not store.deleted
    result = asyncio.run(clean_attempt(
        settings, ledger, record.ingestion_id, store=store, execute=True, confirm_quiescent=True,
    ))
    assert store.deleted == [record.ingestion_id] and result["action"] == "scoped_absence_verified"
    assert ledger.get(record.ingestion_id).state == "cleaned"


def test_completed_ingestion_is_never_deleted(tmp_path):
    settings, ledger, record = setup_attempt(tmp_path)
    ledger.complete(record.ingestion_id)
    store = Store()
    with pytest.raises(LedgerStateError):
        asyncio.run(clean_attempt(settings, ledger, record.ingestion_id, store=store, execute=True))
    assert not store.deleted


def test_preview_refuses_missing_ledger_identity_without_creating_it(tmp_path):
    settings, ledger, record = setup_attempt(tmp_path)
    with pytest.raises(LedgerFormatError, match="no recorded identity"):
        asyncio.run(clean_attempt(settings, ledger, record.ingestion_id))
    with pytest.raises(LedgerFormatError, match="no recorded identity"):
        ledger.identity(create=False)
    assert ledger.get(record.ingestion_id).state == "writing"
