"""Real HTTP/OCR/embedding/Qdrant/SQLite verification in an isolated project.

The runner owns all containers/volumes. Synthetic cleanup records, an injected
manifest failure, a delayed write, and scanned pages are explicit test data;
they are not evidence of an actual Qdrant timeout or a human approval.
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4

import pymupdf
from qdrant_client import models

from app.core.config import Settings
from app.core.embedding_model import MODEL_NAME, MODEL_REVISION
from app.maintenance.cleanup_ingest import clean_attempt
from app.services.ask_retrieval import LedgerRetriever, ManagedRetrievalService
from app.services.ask_service import AskService, CitationEvidence, GeneratedAnswer
from app.services.embedding_async import EmbeddingService
from app.services.ingestion_ledger import IngestionLedger, LedgerError, LedgerStateError, PageRecord
from app.services.ingestion_vectors import IngestionVectorStore, VectorCompatibilityError, VectorStoreError, chunk_id, endpoint_key

CLIENT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE = "http://127.0.0.1:8000"


def check(condition, message):
    if not condition: raise AssertionError(message)
    print("[OK] " + message, flush=True)


def ready():
    for _ in range(150):
        try:
            with CLIENT.open(BASE + "/health", timeout=2) as response:
                if response.status == 200: return
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    raise AssertionError("API did not start")


def post(pdf):
    boundary = "ingest-smoke-" + uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="pdf_file"; filename="sample.pdf"\r\n'
            'Content-Type: application/pdf\r\n\r\n').encode() + pdf + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        BASE + "/api/ingest", data=body, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
    )
    try:
        with CLIENT.open(request, timeout=180) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def scanned_with_empty_first_page():
    with pymupdf.open() as original, pymupdf.open() as scanned:
        page = original.new_page(width=600, height=300)
        page.insert_text((70, 120), "The board reviewed the annual budget on Monday.", fontsize=24)
        pixels = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        scanned.new_page(width=600, height=300)
        target = scanned.new_page(width=600, height=300)
        target.insert_image(target.rect, pixmap=pixels)
        return scanned.tobytes()


async def verify_retrieval(settings, ledger, store, *, partial_fixture):
    """Actual model, Qdrant and SQLite; the answer generator is explicitly fake."""
    embeddings = EmbeddingService(settings)
    managed = ManagedRetrievalService(settings, ledger)
    partial = None
    try:
        vector = await embeddings.embed_query("What did the board discuss in the meeting?")
        retriever = LedgerRetriever(ledger, store, max_candidates=100)
        if partial_fixture:
            partial = ledger.create(
                ingestion_id=str(uuid4()), document_id=str(uuid4()), content_sha256="a" * 64,
                processing_signature="b" * 64, collection=settings.ingest_collection, model_name=MODEL_NAME,
                model_revision=MODEL_REVISION, chunk_tokens=128, overlap_tokens=32,
                endpoint_key=endpoint_key(settings.qdrant_url),
            )
            ledger.record_pages(partial.ingestion_id, [PageRecord(0, True, 1)], physical_pages=1)
            with ledger.lock(store.lock_name):
                ledger.start_writing(partial.ingestion_id)
                await store.upsert([models.PointStruct(
                    id=chunk_id(partial.ingestion_id, 0), vector=vector, payload={
                        "kind": "chunk", "schema_version": 1, "ledger_id": store.ledger_id,
                        "ingestion_id": partial.ingestion_id, "document_id": partial.document_id,
                        "chunk_id": chunk_id(partial.ingestion_id, 0), "chunk_index": 0, "page_number": 0,
                        "index_in_page": 0, "char_start": 0,
                        "char_end": len("Synthetic incomplete ingestion must not be returned"),
                        "model_name": MODEL_NAME, "model_revision": MODEL_REVISION,
                        "processing_signature": partial.processing_signature,
                        "text": "Synthetic incomplete ingestion must not be returned", "source_file": "partial.pdf",
                    },
                )])
            # This exact query vector gives the unfinished point the best score.
        found = await managed.retrieve(vector, limit=5)
        check(bool(found) and all("Synthetic incomplete ingestion" not in item.text for item in found),
              "Real retrieval finds completed fragments and excludes the unfinished fixture"
              if partial_fixture else "Real retrieval finds completed fragments after recreation")
        check(all("página " in item.source and "documento " in item.source for item in found),
              "Real retrieval produces document-specific page references")

        if os.environ.get("SMOKE_ASK_FAKE") == "1":
            # The test-only server injects a fake generator; HTTP, embeddings,
            # retrieval, Qdrant and the ledger are real.
            request = urllib.request.Request(
                BASE + "/api/ask", data=json.dumps({"question": "What did the board discuss?"}).encode(),
                method="POST", headers={"Content-Type": "application/json"},
            )
            # HTTP server runs in another process; keep this event loop available.
            def send_ask():
                with CLIENT.open(request, timeout=180) as response:
                    return response.status, json.load(response)
            status, body = await asyncio.to_thread(send_ask)
            check(status == 200 and body["answer"].startswith("Synthetic smoke answer") and bool(body["sources"]),
                  "Real HTTP ask uses real retrieval and a test-only simulated generator")

        class FakeGenerator:
            async def generate(self, question, context):
                return GeneratedAnswer("Synthetic test answer; no real LLM was called.",
                                       (CitationEvidence(context[0].citation_id, context[0].text[:100]),))

        answer = await AskService(embeddings, managed, FakeGenerator()).ask("What did the board discuss?")
        check(bool(answer.sources) and answer.answer.startswith("Synthetic test answer"),
              "Question pipeline uses real embeddings and retrieval with an explicitly simulated generator")
        if partial_fixture:
            await verify_retrieval_concurrency(settings, ledger, store, retriever, vector, partial)
    finally:
        await managed.aclose()
        if partial is not None:
            # Only the synthetic attempt in disposable smoke resources is removed.
            ledger.fail(partial.ingestion_id, "internal_error")
            await clean_attempt(settings, ledger, partial.ingestion_id, execute=True)
        await embeddings.aclose()


async def verify_retrieval_concurrency(settings, ledger, store, retriever, vector, partial):
    """Use real locks/storage; a gate simulates delay after a real Qdrant response."""
    original_query = store.client.query_points
    started, release = asyncio.Event(), asyncio.Event()

    async def gated_query(**kwargs):
        response = await original_query(**kwargs)
        started.set()
        await release.wait()
        return response

    store.client.query_points = gated_query
    task = asyncio.create_task(retriever.retrieve(vector, limit=5))
    try:
        await asyncio.wait_for(started.wait(), 30)
        try:
            await retriever.retrieve(vector, limit=1)
        except LedgerStateError:
            check(True, "Concurrent retrieval is refused while a real collection lock is held")
        else:
            raise AssertionError("Concurrent retrieval unexpectedly acquired collection lock")
        try:
            await clean_attempt(settings, ledger, partial.ingestion_id, execute=True, store=store)
        except LedgerStateError:
            check(True, "Real cleanup is blocked by the active retrieval collection lock")
        else:
            raise AssertionError("Cleanup unexpectedly acquired collection lock")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            check(True, "Cancellation of delayed retrieval is propagated")
        else:
            raise AssertionError("Cancelled retrieval unexpectedly completed")
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        store.client.query_points = original_query
    check(bool(await retriever.retrieve(vector, limit=1)), "Real retrieval succeeds after cancellation releases the lock")

    # Failure is real (unreachable address), not a Qdrant server timeout.
    unavailable_settings = settings.model_copy(update={"qdrant_url": "http://127.0.0.1:1", "qdrant_read_retries": 0})
    unavailable = IngestionVectorStore(unavailable_settings, store.ledger_id)
    try:
        try:
            await LedgerRetriever(ledger, unavailable).retrieve(vector, limit=1)
        except VectorStoreError:
            check(True, "Unreachable Qdrant returns a controlled failure")
        else:
            raise AssertionError("Unreachable Qdrant was treated as a successful search")
    finally:
        await unavailable.aclose()
    missing_ledger = IngestionLedger(Path(settings.ingestion_ledger_path).parent / "synthetic-missing.sqlite3")
    try:
        await LedgerRetriever(missing_ledger, store).retrieve(vector, limit=1)
    except LedgerError:
        check(True, "Missing ledger fails closed without creating a database")
    else:
        raise AssertionError("Missing ledger was treated as a successful search")
    check(not missing_ledger.path.exists(), "Missing ledger database was not created")


async def inspect_stage(mode):
    settings = Settings()
    ledger = IngestionLedger(settings.ingestion_ledger_path)
    state_path = Path(settings.ingestion_ledger_path).parent / "smoke_state.json"
    if mode == "seed":
        inputs = [Path("/samples/meeting_minutes.pdf").read_bytes(), Path("/samples/company_memo.pdf").read_bytes()]
        for data in inputs:
            status, result = post(data)
            check(status == 200 and result["status"] == "success" and result["chunks_stored"] > 0,
                  "Real HTTP ingestion stored a sample PDF")
        status, _ = post(inputs[0])
        check(status == 200, "Reingestion is a separate successful attempt")
        duplicates = ledger.find_by_content(hashlib.sha256(inputs[0]).hexdigest())
        check(len(duplicates) == 2 and len({r.document_id for r in duplicates}) == 2,
              "Identical PDF bytes retain two document identities")
        synthetic = scanned_with_empty_first_page()
        status, result = post(synthetic)
        check(status == 200 and result["chunks_stored"] > 0, "A synthetic scan with an empty first page is accepted")
        record = ledger.find_by_content(hashlib.sha256(synthetic).hexdigest())[0]
        check(ledger.pages(record.ingestion_id)[0] == PageRecord(0, False, 0)
              and ledger.pages(record.ingestion_id)[1].page_number == 1, "Empty physical page is persisted without fragments")
        check(post(b"not a pdf")[0] == 400, "Invalid PDF returns 400")
        with pymupdf.open() as empty:
            empty.new_page()
            check(post(empty.tobytes())[0] == 422, "Document with no detected text returns 422")
        records = [r for data in inputs for r in ledger.find_by_content(hashlib.sha256(data).hexdigest())] + [record]
        state = {"ids": [r.ingestion_id for r in records], "synthetic_id": record.ingestion_id}
    else:
        state = json.loads(state_path.read_text())

    store = IngestionVectorStore(settings, ledger.identity())
    try:
        await store.ensure(create=False)
        for ingestion_id in state["ids"]:
            record = ledger.get(ingestion_id)
            check(record.state == "completed", "Ingestion completion is persistent in SQLite")
            await store.verify(record)
        check(True, "All completed documents retain their point IDs in Qdrant")
        scanned_record = ledger.get(state["synthetic_id"])
        empty_page_points = await store.client.count(settings.ingest_collection, exact=True, count_filter=models.Filter(must=[
            store.attempt_filter(scanned_record), models.FieldCondition(key="page_number", match=models.MatchValue(value=0)),
        ]))
        check(empty_page_points.count == 0, "No Qdrant points refer to the empty physical page")
        await verify_retrieval(settings, ledger, store, partial_fixture=mode == "seed")
        if mode == "verify":
            check(True, "SQLite and Qdrant survived container recreation using their dedicated volumes")
            return

        other = IngestionVectorStore(settings, str(uuid4()))
        try:
            try:
                await other.ensure(create=True)
            except VectorCompatibilityError:
                check(True, "Another ledger cannot adopt the owned collection")
            else:
                raise AssertionError("Another ledger was accepted")
        finally:
            await other.aclose()

        untagged_id = str(uuid4())
        await store.client.upsert(settings.ingest_collection, points=[models.PointStruct(
            id=untagged_id, vector=[1.0] + [0.0] * 383, payload={"synthetic": "untagged fixture"},
        )], wait=True)
        try:
            await store.ensure(create=True)
        except VectorCompatibilityError:
            check(True, "Untagged points are detected without deleting or overwriting the collection")
        else:
            raise AssertionError("Untagged point was silently accepted")
        finally:
            await store.client.delete(settings.ingest_collection, points_selector=[untagged_id], wait=True)
        wrong_name = "incompatible_" + uuid4().hex
        await store.client.create_collection(wrong_name, vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE))
        incompatible = IngestionVectorStore(settings.model_copy(update={"ingest_collection": wrong_name}), store.ledger_id)
        try:
            try:
                await incompatible.ensure(create=True)
            except VectorCompatibilityError:
                check(True, "A pre-existing collection with another dimension is refused")
            else:
                raise AssertionError("Incompatible dimensions were accepted")
        finally:
            await incompatible.aclose()

        # Inject a client-side failure before the manifest write. The collection
        # itself is real; subsequent attempts must not adopt the unmarked data.
        failed_name = "unmarked_" + uuid4().hex
        failed_store = IngestionVectorStore(settings.model_copy(update={"ingest_collection": failed_name}), store.ledger_id)
        original_upsert = failed_store.client.upsert
        async def fail_manifest(**kwargs):
            raise TimeoutError("synthetic manifest write failure")
        failed_store.client.upsert = fail_manifest
        try:
            try:
                await failed_store.ensure(create=True)
            except VectorStoreError:
                pass
            else:
                raise AssertionError("Injected manifest failure was not surfaced")
            failed_store.client.upsert = original_upsert
            check(await failed_store.client.collection_exists(failed_name), "Manifest failure leaves the real collection intact")
            try:
                await failed_store.ensure(create=True)
            except VectorCompatibilityError:
                check(True, "A collection left without a manifest is not adopted")
            else:
                raise AssertionError("Unmarked collection was adopted after manifest failure")
        finally:
            await failed_store.aclose()

        # Conversely, a write can succeed remotely even if the client reports a
        # timeout. A later check may accept only the fully matching manifest.
        ambiguous_name = "manifest_timeout_" + uuid4().hex
        ambiguous = IngestionVectorStore(settings.model_copy(update={"ingest_collection": ambiguous_name}), store.ledger_id)
        original_upsert = ambiguous.client.upsert
        async def send_then_timeout(**kwargs):
            await original_upsert(**kwargs)
            raise TimeoutError("synthetic timeout after confirmed manifest write")
        ambiguous.client.upsert = send_then_timeout
        try:
            try:
                await ambiguous.ensure(create=True)
            except VectorStoreError:
                pass
            else:
                raise AssertionError("Injected post-write timeout was not surfaced")
            ambiguous.client.upsert = original_upsert
            await ambiguous.ensure(create=True)
            check(True, "A matching manifest written before an injected timeout is verified on retry")
        finally:
            await ambiguous.aclose()

        # Synthetic partial-write ledger in the real store. An additional point
        # is intentionally sent after the simulated timeout/preview to exercise
        # a late arrival. No actual Qdrant server timeout is induced.
        partial = ledger.create(
            ingestion_id=str(uuid4()), document_id=str(uuid4()), content_sha256="c" * 64,
            processing_signature="d" * 64, collection=settings.ingest_collection, model_name=MODEL_NAME,
            model_revision=MODEL_REVISION, chunk_tokens=128, overlap_tokens=32,
            endpoint_key=endpoint_key(settings.qdrant_url),
        )
        ledger.record_pages(partial.ingestion_id, [PageRecord(0, True, 2)], physical_pages=1)
        ledger.start_writing(partial.ingestion_id)
        ledger.write_intent(partial.ingestion_id)
        await store.upsert([models.PointStruct(
            id=chunk_id(partial.ingestion_id, 0), vector=[1.0] + [0.0] * 383, payload={
                "kind": "chunk", "schema_version": 1, "ledger_id": store.ledger_id,
                "ingestion_id": partial.ingestion_id, "document_id": partial.document_id,
                "model_name": MODEL_NAME, "model_revision": MODEL_REVISION, "text": "Synthetic partial-write fixture",
            },
        )])
        ledger.fail(partial.ingestion_id, "qdrant_timeout")
        inventory = subprocess.run([
            sys.executable, "-m", "app.maintenance.cleanup_ingest", "--pending",
        ], capture_output=True, text=True, timeout=60)
        check(inventory.returncode == 0 and any(row["ingestion_id"] == partial.ingestion_id
              for row in json.loads(inventory.stdout)), "Real cleanup CLI inventories pending attempts")
        preview = await clean_attempt(settings, ledger, partial.ingestion_id)
        check(preview["points"] == 1 and await store.count(partial) == 1, "Cleanup preview does not delete points")
        try:
            await clean_attempt(settings, ledger, partial.ingestion_id, execute=True)
        except LedgerStateError:
            check(True, "Unknown write outcomes block automatic deletion")
        else:
            raise AssertionError("Unconfirmed cleanup was allowed")
        await store.upsert([models.PointStruct(
            id=chunk_id(partial.ingestion_id, 1), vector=[1.0] + [0.0] * 383, payload={
                "kind": "chunk", "schema_version": 1, "ledger_id": store.ledger_id,
                "ingestion_id": partial.ingestion_id, "document_id": partial.document_id,
                "model_name": MODEL_NAME, "model_revision": MODEL_REVISION, "text": "Synthetic delayed-write fixture",
            },
        )])
        check(await store.count(partial) == 2 and ledger.get(partial.ingestion_id).write_uncertain,
              "A simulated late write reaches real Qdrant while uncertainty remains recorded")
        try:
            await clean_attempt(settings, ledger, partial.ingestion_id, execute=True)
        except LedgerStateError:
            check(True, "A late arrival does not disable the quiescence guard")
        else:
            raise AssertionError("Late write allowed unconfirmed cleanup")
        with ledger.attempt_lock(partial.ingestion_id):
            try:
                await clean_attempt(settings, ledger, partial.ingestion_id, execute=True, confirm_quiescent=True)
            except LedgerStateError:
                check(True, "Active ownership blocks cleanup even with confirmation")
            else:
                raise AssertionError("Active ingestion was not protected")
        result = subprocess.run([
            sys.executable, "-m", "app.maintenance.cleanup_ingest", "--id", partial.ingestion_id,
            "--execute", "--confirm-quiescent",
        ], capture_output=True, text=True, timeout=60)
        check(result.returncode == 0 and await store.count(partial) == 0
              and ledger.get(partial.ingestion_id).state == "cleaned", "Real cleanup CLI deletes only the selected failed attempt")
        for ingestion_id in state["ids"]:
            await store.verify(ledger.get(ingestion_id))
        check(True, "Cleanup preserved all completed documents and the manifest")
        try:
            await clean_attempt(settings, ledger, state["ids"][0], execute=True, confirm_quiescent=True)
        except LedgerStateError:
            check(True, "Completed ingestion cannot be deleted by cleanup")
        else:
            raise AssertionError("Completed ingestion was deletable")
        state_path.write_text(json.dumps(state))
    finally:
        await store.aclose()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"seed", "verify"}:
        raise SystemExit("Usage: verificar_ingestion.py seed|verify")
    ready()
    asyncio.run(inspect_stage(sys.argv[1]))
