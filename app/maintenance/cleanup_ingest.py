"""Scoped cleanup, dry-run by default, using the same locks as ingestion."""

import argparse
import asyncio
import json

from app.core.config import Settings
from app.core.embedding_model import MODEL_NAME, MODEL_REVISION
from app.services.ingestion_ledger import IngestionLedger, LedgerStateError
from app.services.ingestion_vectors import IngestionVectorStore, endpoint_key
from app.services.ocr_service import _run_blocking


async def clean_attempt(settings, ledger, ingestion_id, *, execute=False, confirm_quiescent=False, store=None):
    """Aging is not proof of inactivity; attempt_lock is mandatory even for preview."""
    with ledger.attempt_lock(ingestion_id):
        record = await _run_blocking(ledger.get, ingestion_id)
        if record.state in {"completed", "cleaned"}:
            raise LedgerStateError("Completed or already-cleaned ingestions cannot be deleted")
        if (record.collection != settings.ingest_collection or record.endpoint_key != endpoint_key(settings.qdrant_url)
                or record.model_name != MODEL_NAME or record.model_revision != MODEL_REVISION):
            raise LedgerStateError("Configuration does not match the recorded collection, endpoint and model")
        if record.state in {"processing", "failed"}:
            if execute and record.state == "processing":
                await _run_blocking(ledger.recover, ingestion_id)
            return {"ingestion_id": ingestion_id, "state": record.state, "points": 0, "action": "no_vector_writes_recorded"}
        if record.state not in {"writing", "cleanup_pending"}:
            raise LedgerStateError("Ingestion is not eligible for cleanup")
        client = store or IngestionVectorStore(settings, await _run_blocking(lambda: ledger.identity(create=False)))
        try:
            with ledger.lock(client.lock_name):
                await client.ensure(create=False)
                count = await client.count(record)
                result = {
                    "ingestion_id": ingestion_id, "state": record.state, "points": count,
                    "write_uncertain": bool(record.write_uncertain), "action": "preview",
                }
                if not execute:
                    return result
                if record.write_uncertain and not confirm_quiescent:
                    raise LedgerStateError(
                        "Unknown write outcome: stop writers, drain/restart Qdrant and verify quiescence before --confirm-quiescent"
                    )
                # Do not clear uncertainty before the delete: if maintenance is
                # interrupted, another run must still require the confirmation.
                await _run_blocking(ledger.recover, ingestion_id)
                await client.clear_points(record)
                await _run_blocking(ledger.mark_cleaned, ingestion_id)
                result["action"] = "scoped_absence_verified"
                result["points"] = 0
                return result
        finally:
            if store is None:
                await client.aclose()


async def run(args):
    settings = Settings()
    ledger = IngestionLedger(settings.ingestion_ledger_path)
    # Never initialize/create a new database during maintenance.
    if args.pending:
        if args.execute or args.confirm_quiescent:
            raise ValueError("--pending is inventory only; select a single --id before executing")
        print(json.dumps([{
            "ingestion_id": record.ingestion_id, "state": record.state,
            "write_uncertain": bool(record.write_uncertain), "updated_at": record.updated_at,
        } for record in ledger.pending()]))
        return
    result = await clean_attempt(
        settings, ledger, args.id, execute=args.execute, confirm_quiescent=args.confirm_quiescent,
    )
    print(json.dumps(result, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--id", help="Exact ingestion UUID from the operational log or SQLite ledger")
    target.add_argument("--pending", action="store_true", help="List up to 100 pending IDs; never deletes or infers inactivity")
    parser.add_argument("--execute", action="store_true", help="Delete only this failed ingestion; default is read-only preview")
    parser.add_argument("--confirm-quiescent", action="store_true", help="Operator confirms no pending remote writes can arrive")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as error:
        # Domain errors contain no document contents or credentials.
        from app.services.ingestion_ledger import LedgerError
        from app.services.ingestion_vectors import VectorStoreError
        if isinstance(error, (LedgerError, VectorStoreError, ValueError)):
            raise SystemExit(f"Cleanup refused or unconfirmed: {type(error).__name__}: {error}") from None
        raise SystemExit("Cleanup failed; inspect the ledger without assuming point deletion succeeded") from None


if __name__ == "__main__":
    main()
