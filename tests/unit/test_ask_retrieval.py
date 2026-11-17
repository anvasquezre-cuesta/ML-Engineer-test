import asyncio
from contextlib import contextmanager
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.embedding_model import MODEL_NAME, MODEL_REVISION
from app.core.config import Settings
from app.services.ask_retrieval import LedgerRetriever, ManagedRetrievalService
from app.services.ingestion_vectors import VectorCompatibilityError, VectorStoreError, chunk_id
from app.services.ingestion_ledger import IngestionLedger, LedgerError, LedgerStateError, PageRecord


class Ledger:
    def __init__(self, records):
        self.records, self.locked = records, False

    @contextmanager
    def lock(self, name):
        assert name == "collection-test" and not self.locked
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    def identity(self, *, create):
        assert self.locked and not create
        return "ledger"

    def get(self, ingestion_id):
        assert self.locked
        return self.records[ingestion_id]

    def pages(self, ingestion_id):
        assert self.locked
        return [PageRecord(0, True, 1)]


class Store:
    ledger_id = "ledger"
    lock_name = "collection-test"
    collection = "collection"
    endpoint = "endpoint"
    settings = SimpleNamespace(qdrant_timeout_seconds=10, ingest_max_page_chars=1000)

    def __init__(self, ledger, points):
        self.ledger, self.points = ledger, points
        self.client = SimpleNamespace(query_points=self.query_points)

    def _condition(self, key, value):
        from qdrant_client import models
        return models.FieldCondition(key=key, match=models.MatchValue(value=value))

    async def ensure(self, *, create):
        assert self.ledger.locked and not create

    async def _call(self, fn, *, read, **kwargs):
        assert self.ledger.locked and read
        return await fn(**kwargs)

    async def query_points(self, **kwargs):
        assert kwargs["limit"] == 10 and kwargs["with_vectors"] is False
        return SimpleNamespace(points=self.points)


def candidate(state="completed", *, text="private fragment", score=0.9):
    ingestion, document = str(uuid4()), str(uuid4())
    cid = chunk_id(ingestion, 0)
    record = SimpleNamespace(document_id=document, collection="collection", endpoint_key="endpoint",
                             model_name=MODEL_NAME, model_revision=MODEL_REVISION,
                             processing_signature="signature", state=state, write_uncertain=False,
                             expected_chunks=1, physical_pages=1)
    payload = {"kind": "chunk", "schema_version": 1, "ledger_id": "ledger", "ingestion_id": ingestion,
               "document_id": document, "chunk_id": cid, "chunk_index": 0, "page_number": 0,
               "index_in_page": 0, "char_start": 0, "char_end": len(text),
               "model_name": MODEL_NAME, "model_revision": MODEL_REVISION, "processing_signature": "signature",
               "text": text, "source_file": "test.pdf"}
    return ingestion, record, SimpleNamespace(id=cid, payload=payload, score=score)


def retrieve(items, limit=1):
    ledger = Ledger({ingestion: record for ingestion, record, _ in items})
    store = Store(ledger, [point for _, _, point in items])
    result = asyncio.run(LedgerRetriever(ledger, store, max_candidates=10).retrieve([1.0] * 384, limit=limit))
    assert not ledger.locked
    return result


def test_skips_incomplete_attempt_and_returns_completed_candidate():
    unfinished = candidate("writing", score=0.99)
    completed = candidate(text="eligible", score=0.8)
    result = retrieve([unfinished, completed])
    assert len(result) == 1 and result[0].text == "eligible"
    assert "página 1" in result[0].source and completed[1].document_id in result[0].source


@pytest.mark.parametrize("state", ["processing", "writing", "failed", "cleanup_pending", "cleaned"])
def test_noncompleted_ingestion_never_returns_text(state):
    assert retrieve([candidate(state)]) == []


def test_inconsistent_ledger_identity_fails_closed():
    item = candidate()
    item[1].document_id = str(uuid4())
    with pytest.raises(VectorCompatibilityError):
        retrieve([item])


@pytest.mark.parametrize("field,value", [
    ("collection", "other"), ("endpoint_key", "other"), ("model_name", "other"),
    ("model_revision", "other"), ("processing_signature", "other"),
])
def test_record_configuration_mismatch_is_rejected(field, value):
    item = candidate()
    setattr(item[1], field, value)
    with pytest.raises(VectorCompatibilityError, match="identity"):
        retrieve([item])


@pytest.mark.parametrize("field,value", [("chunk_id", "bad"), ("page_number", -1), ("text", ""),
                                        ("source_file", "x\nheader"), ("schema_version", 2)])
def test_invalid_payload_fails_closed_without_leaking_text(field, value):
    item = candidate()
    item[2].payload[field] = value
    with pytest.raises(VectorStoreError, match="^Invalid vector payload$"):
        retrieve([item])


def test_completed_attempt_with_unconfirmed_write_is_rejected():
    item = candidate()
    item[1].write_uncertain = True
    with pytest.raises(VectorCompatibilityError):
        retrieve([item])


@pytest.mark.parametrize("field,value", [
    ("index_in_page", 1), ("chunk_index", 1), ("page_number", 1),
    ("char_start", -1), ("char_end", 1), ("index_in_page", True),
])
def test_inconsistent_fragment_coordinates_fail_closed(field, value):
    item = candidate()
    item[2].payload[field] = value
    with pytest.raises((VectorStoreError, VectorCompatibilityError)):
        retrieve([item])


def test_ledger_page_counts_must_match_fragment(monkeypatch):
    monkeypatch.setattr(Ledger, "pages", lambda self, _: [PageRecord(0, False, 0)])
    with pytest.raises(VectorCompatibilityError, match="page metadata"):
        retrieve([candidate()])


def test_exhausted_candidate_budget_is_not_reported_as_no_evidence():
    with pytest.raises(VectorStoreError, match="Candidate search limit"):
        retrieve([candidate("writing") for _ in range(10)])


def test_missing_ingestion_record_fails_closed():
    item = candidate()
    ledger = Ledger({})
    def missing(_):
        raise LedgerStateError("Ingestion does not exist")
    ledger.get = missing
    store = Store(ledger, [item[2]])
    with pytest.raises(LedgerStateError):
        asyncio.run(LedgerRetriever(ledger, store, max_candidates=10).retrieve([1.0] * 384, limit=1))
    assert not ledger.locked


@pytest.mark.parametrize("failure", [LedgerError("Ledger unavailable"), VectorStoreError("Qdrant unavailable")])
def test_dependency_failure_releases_lock_and_is_not_no_evidence(failure):
    ledger = Ledger({})
    store = Store(ledger, [])
    async def broken(*args, **kwargs):
        raise failure
    store.ensure = broken
    with pytest.raises(type(failure)):
        asyncio.run(LedgerRetriever(ledger, store, max_candidates=10).retrieve([1.0] * 384, limit=1))
    assert not ledger.locked


@pytest.mark.parametrize("cancel", [False, True])
def test_cancellation_or_timeout_releases_collection_lock(cancel):
    async def run():
        ledger = Ledger({})
        store = Store(ledger, [])
        started = asyncio.Event()
        async def blocked(**kwargs):
            started.set()
            await asyncio.Event().wait()
        store.client.query_points = blocked
        retrieval = LedgerRetriever(ledger, store, max_candidates=10)
        task = asyncio.create_task(retrieval.retrieve([1.0] * 384, limit=1))
        await asyncio.wait_for(started.wait(), 1)
        assert ledger.locked
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(task, 0.01)
        assert not ledger.locked
        store.client.query_points = store.query_points
        assert await retrieval.retrieve([1.0] * 384, limit=1) == []
    asyncio.run(run())


def test_real_collection_lock_contention_refuses_retrieval(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    ledger = IngestionLedger(directory / "ledger.sqlite3")
    ledger.initialize()
    store = SimpleNamespace(lock_name="collection-test")
    with ledger.lock(store.lock_name):
        with pytest.raises(LedgerStateError):
            asyncio.run(LedgerRetriever(ledger, store, max_candidates=10).retrieve([1.0] * 384, limit=1))
    with ledger.lock(store.lock_name):
        pass


def test_cancel_waits_for_blocking_ledger_read_before_releasing_lock():
    async def run():
        item = candidate()
        ledger = Ledger({item[0]: item[1]})
        store = Store(ledger, [item[2]])
        started, release = threading.Event(), threading.Event()
        original = ledger.get

        def blocked(ingestion_id):
            started.set()
            if not release.wait(3):
                raise RuntimeError("Test timed out")
            return original(ingestion_id)

        ledger.get = blocked
        task = asyncio.create_task(LedgerRetriever(ledger, store, max_candidates=10).retrieve([1.0] * 384, limit=1))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            assert ledger.locked and not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not ledger.locked
    asyncio.run(run())


@pytest.mark.parametrize("response", [None, SimpleNamespace(points=None), SimpleNamespace(points=[object()])])
def test_malformed_qdrant_result_is_a_controlled_error(response):
    ledger = Ledger({})
    store = Store(ledger, [])
    async def bad(**kwargs):
        return response
    store.client.query_points = bad
    with pytest.raises(VectorStoreError):
        asyncio.run(LedgerRetriever(ledger, store, max_candidates=10).retrieve([1.0] * 384, limit=1))
    assert not ledger.locked


@pytest.mark.parametrize("score", [float("nan"), float("inf"), True, None])
def test_invalid_score_is_rejected(score):
    item = candidate(score=score)
    with pytest.raises(VectorStoreError, match="score"):
        retrieve([item])


def test_equal_scores_have_stable_id_order_and_distinct_document_sources():
    first, second = candidate(text="same content"), candidate(text="same content")
    expected = sorted([first, second], key=lambda item: str(item[2].id))
    forward = retrieve([first, second], limit=2)
    reverse = retrieve([second, first], limit=2)
    assert forward == reverse
    assert all(item[1].document_id in result.source for item, result in zip(expected, forward, strict=True))
    assert forward[0].source != forward[1].source


def test_incompatible_manifest_stops_before_vector_query():
    ledger = Ledger({})
    store = Store(ledger, [])
    async def incompatible(*, create):
        assert not create
        raise VectorCompatibilityError("Incompatible manifest")
    store.ensure = incompatible
    async def never_query(**kwargs):
        raise AssertionError("Must not query incompatible collection")
    store.client.query_points = never_query
    with pytest.raises(VectorCompatibilityError):
        asyncio.run(LedgerRetriever(ledger, store, max_candidates=10).retrieve([1.0] * 384, limit=1))
    assert not ledger.locked


def test_managed_retrieval_is_lazy_and_closes_its_client():
    async def run():
        item = candidate()
        ledger = Ledger({item[0]: item[1]})
        ledger.identity = lambda *, create: "ledger" if not create else None
        stores = []
        def factory(settings, identity):
            assert identity == "ledger"
            store = Store(ledger, [item[2]])
            store.closed = False
            async def close():
                store.closed = True
            store.aclose = close
            stores.append(store)
            return store
        service = ManagedRetrievalService(Settings(ask_max_candidates=10), ledger, store_factory=factory)
        assert not stores
        assert len(await service.retrieve([1.0] * 384, limit=1)) == 1
        assert stores[0].closed and not ledger.locked
        await service.aclose()
        with pytest.raises(VectorStoreError, match="shutting down"):
            await service.retrieve([1.0] * 384, limit=1)
    asyncio.run(run())


def test_managed_retrieval_shutdown_cancels_inflight_and_closes_client():
    async def run():
        ledger = Ledger({})
        ledger.identity = lambda *, create: "ledger" if not create else None
        started = asyncio.Event()
        stores = []
        def factory(settings, identity):
            store = Store(ledger, [])
            store.closed = False
            async def block(**kwargs):
                started.set()
                await asyncio.Event().wait()
            async def close():
                store.closed = True
            store.client.query_points, store.aclose = block, close
            stores.append(store)
            return store
        service = ManagedRetrievalService(Settings(ask_max_candidates=10), ledger, store_factory=factory)
        task = asyncio.create_task(service.retrieve([1.0] * 384, limit=1))
        await asyncio.wait_for(started.wait(), 2)
        await service.aclose()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stores[0].closed and not ledger.locked
    asyncio.run(run())


def test_managed_retrieval_missing_ledger_never_initializes_database(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    ledger = IngestionLedger(directory / "missing.sqlite3")
    def factory(*args):
        raise AssertionError("No Qdrant client should be created")
    service = ManagedRetrievalService(Settings(), ledger, store_factory=factory)
    with pytest.raises(LedgerError):
        asyncio.run(service.retrieve([1.0] * 384, limit=1))
    assert not ledger.path.exists()
