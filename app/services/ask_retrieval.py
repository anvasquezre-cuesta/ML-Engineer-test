"""Bounded, read-only Qdrant retrieval checked against the ingestion ledger.

Only cooperating writers using the same host and collection lock are supported.
The caller owns the ledger and vector-store lifecycle; no collection is created.
"""

import asyncio
import math
from uuid import UUID

from qdrant_client import models

from app.core.embedding_model import MODEL_DIMENSIONS, MODEL_NAME, MODEL_REVISION
from app.services.ask_service import RetrievedFragment
from app.services.ingestion_vectors import IngestionVectorStore, VectorCompatibilityError, VectorStoreError, chunk_id
from app.services.ocr_service import _finish_cancelled_task, _run_blocking


class LedgerRetriever:
    def __init__(self, ledger, store, *, max_candidates: int = 100):
        if type(max_candidates) is not int or not 1 <= max_candidates <= 1000:
            raise ValueError("Invalid candidate limit")
        self.ledger, self.store, self.max_candidates = ledger, store, max_candidates

    async def retrieve(self, vector: list[float], *, limit: int) -> list[RetrievedFragment]:
        if (type(limit) is not int or not 1 <= limit <= self.max_candidates
                or not isinstance(vector, list) or len(vector) != MODEL_DIMENSIONS
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)
                or not any(vector)):
            raise ValueError("Invalid retrieval input")
        store = self.store
        # The nonblocking collection lock spans both Qdrant and ledger reads.
        # Ingestion and maintenance acquire this same lock for mutations.
        with self.ledger.lock(store.lock_name):
            identity = await _run_blocking(lambda: self.ledger.identity(create=False))
            if identity != store.ledger_id:
                raise VectorCompatibilityError("Ledger identity does not match vector collection")
            await store.ensure(create=False)
            conditions = [store._condition(key, value) for key, value in (
                ("kind", "chunk"), ("schema_version", 1), ("ledger_id", store.ledger_id),
                ("model_name", MODEL_NAME), ("model_revision", MODEL_REVISION),
            )]
            result = await store._call(
                store.client.query_points, read=True, collection_name=store.collection,
                query=vector, query_filter=models.Filter(must=conditions),
                limit=self.max_candidates, with_payload=True, with_vectors=False,
                timeout=store.settings.qdrant_timeout_seconds,
            )
            points = getattr(result, "points", None)
            if not isinstance(points, list) or len(points) > self.max_candidates:
                raise VectorStoreError("Invalid vector search result")
            ordered = []
            for point in points:
                score = getattr(point, "score", None)
                if type(score) not in (int, float) or not math.isfinite(score) or getattr(point, "id", None) is None:
                    raise VectorStoreError("Invalid vector search score")
                ordered.append(point)
            ordered.sort(key=lambda point: (-point.score, str(point.id)))
            records, page_records, selected = {}, {}, []
            for point in ordered:
                payload = point.payload
                if not isinstance(payload, dict):
                    raise VectorStoreError("Invalid vector payload")
                try:
                    ingestion_id = str(UUID(payload["ingestion_id"]))
                    document_id = str(UUID(payload["document_id"]))
                    index, page = payload["chunk_index"], payload["page_number"]
                    page_index, start, end = payload["index_in_page"], payload["char_start"], payload["char_end"]
                    if (type(index) is not int or index < 0 or type(page) is not int or page < 0
                            or type(page_index) is not int or page_index < 0
                            or type(start) is not int or type(end) is not int or start < 0 or end <= start
                            or payload["chunk_id"] != chunk_id(ingestion_id, index)
                            or str(point.id) != payload["chunk_id"]
                            or payload["kind"] != "chunk" or type(payload["schema_version"]) is not int
                            or payload["schema_version"] != 1
                            or payload["ledger_id"] != identity or payload["model_name"] != MODEL_NAME
                            or payload["model_revision"] != MODEL_REVISION):
                        raise ValueError
                    text, filename = payload["text"], payload["source_file"]
                    if (not isinstance(text, str) or not text.strip() or len(text) > store.settings.ingest_max_page_chars
                            or end - start != len(text) or end > store.settings.ingest_max_page_chars
                            or not isinstance(filename, str) or not filename.strip() or len(filename) > 255
                            or any(ord(c) < 32 or ord(c) == 127 for c in filename)):
                        raise ValueError
                except (ValueError, TypeError, KeyError, AttributeError):
                    raise VectorStoreError("Invalid vector payload") from None
                if ingestion_id not in records:
                    records[ingestion_id] = await _run_blocking(self.ledger.get, ingestion_id)
                record = records[ingestion_id]
                if (record.document_id != document_id or record.collection != store.collection
                        or record.endpoint_key != store.endpoint or record.model_name != MODEL_NAME
                        or record.model_revision != MODEL_REVISION
                        or record.processing_signature != payload.get("processing_signature")):
                    raise VectorCompatibilityError("Vector identity does not match ingestion ledger")
                if record.state != "completed":
                    continue
                if (record.write_uncertain or type(record.expected_chunks) is not int
                        or index >= record.expected_chunks or type(record.physical_pages) is not int
                        or page >= record.physical_pages):
                    raise VectorCompatibilityError("Invalid completed ingestion metadata")
                if ingestion_id not in page_records:
                    page_records[ingestion_id] = await _run_blocking(self.ledger.pages, ingestion_id)
                pages = page_records[ingestion_id]
                if (len(pages) != record.physical_pages
                        or any(type(item.page_number) is not int or item.page_number != number
                               or type(item.text_detected) is not bool or type(item.chunk_count) is not int
                               or item.chunk_count < 0 or (not item.text_detected and item.chunk_count != 0)
                               for number, item in enumerate(pages))
                        or sum(item.chunk_count for item in pages) != record.expected_chunks
                        or not pages[page].text_detected or page_index >= pages[page].chunk_count
                        or index != sum(item.chunk_count for item in pages[:page]) + page_index):
                    raise VectorCompatibilityError("Vector page metadata does not match ingestion ledger")
                selected.append(RetrievedFragment(text, f"{filename} — página {page + 1} — documento {document_id}"))
                if len(selected) == limit:
                    break
            if len(selected) < limit and len(points) == self.max_candidates:
                # More eligible points may be hidden beyond the bounded search.
                # Do not misreport an incomplete search as absence of evidence.
                raise VectorStoreError("Candidate search limit reached before retrieval was complete")
            return selected


class ManagedRetrievalService:
    """Lifespan-managed, lazy retrieval; each request owns its Qdrant client."""

    def __init__(self, settings, ledger, *, store_factory=IngestionVectorStore):
        self.settings, self.ledger, self.store_factory = settings, ledger, store_factory
        self._closing = False
        self._tasks: set[asyncio.Task] = set()

    async def retrieve(self, vector: list[float], *, limit: int) -> list[RetrievedFragment]:
        if self._closing:
            raise VectorStoreError("Retrieval service is shutting down")
        task = asyncio.create_task(self._retrieve(vector, limit=limit))
        self._tasks.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.cancelling():
                task.cancel()
            await _finish_cancelled_task(task)
            raise
        finally:
            self._tasks.discard(task)

    async def _retrieve(self, vector, *, limit):
        # Never initialize the ledger or collection as a side effect of asking.
        identity = await _run_blocking(lambda: self.ledger.identity(create=False))
        store = self.store_factory(self.settings, identity)
        try:
            return await LedgerRetriever(self.ledger, store, max_candidates=self.settings.ask_max_candidates).retrieve(
                vector, limit=limit,
            )
        finally:
            close = asyncio.create_task(store.aclose())
            try:
                await asyncio.shield(close)
            except asyncio.CancelledError:
                await _finish_cancelled_task(close)
                raise

    async def aclose(self):
        self._closing = True
        tasks = tuple(self._tasks)
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
