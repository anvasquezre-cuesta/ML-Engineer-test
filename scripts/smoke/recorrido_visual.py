"""Real, step-by-step ingestion fixtures for the isolated visual walkthrough."""

import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

from qdrant_client import models

from app.core.config import Settings
from app.services.ingestion_ledger import IngestionLedger, PageRecord
from app.services.ingestion_vectors import IngestionVectorStore, chunk_id
from verificar_ingestion import post, scanned_with_empty_first_page


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def describe(ledger, record, response):
    print(json.dumps({
        "respuesta_http": response,
        "ingestion_id": record.ingestion_id,
        "document_id": record.document_id,
        "sha256_pdf": record.content_sha256,
        "estado": record.state,
        "fragmentos_esperados": record.expected_chunks,
        "paginas": [asdict(page) for page in ledger.pages(record.ingestion_id)],
    }, indent=2, ensure_ascii=False), flush=True)


def ingest_sample(*, duplicate):
    data = Path("/samples/meeting_minutes.pdf").read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    ledger = IngestionLedger(Settings().ingestion_ledger_path)
    previous = ledger.find_by_content(digest) if ledger.path.exists() else []
    if duplicate:
        require(bool(previous), "Primero ingiere el PDF de ejemplo")
    status, response = post(data)
    require(status == 200 and response.get("chunks_stored", 0) > 0, "La ingesta del PDF falló")
    records = ledger.find_by_content(digest)
    previous_ids = {record.ingestion_id for record in previous}
    new = [record for record in records if record.ingestion_id not in previous_ids]
    require(len(new) == 1 and new[0].state == "completed", "No se registró una ingesta completada nueva")
    if duplicate:
        require(all(record.document_id != new[0].document_id for record in previous), "El documento no tiene un ID nuevo")
        print("[OK] Mismo SHA-256, nuevo ingestion_id y document_id.")
    else:
        print("[OK] PDF ingerido mediante HTTP, OCR, embeddings y Qdrant reales.")
    describe(ledger, new[0], response)
    if not duplicate:
        asyncio.run(check_vector(Settings(), ledger, new[0]))


async def check_vector(settings, ledger, record):
    store = IngestionVectorStore(settings, ledger.identity(create=False))
    point_id = chunk_id(record.ingestion_id, 0)
    try:
        await store.ensure(create=False)
        points = await store.client.retrieve(settings.ingest_collection, ids=[point_id], with_vectors=True)
        require(len(points) == 1 and isinstance(points[0].vector, list) and len(points[0].vector) == 384,
                "El fragmento no tiene un vector de 384 dimensiones")
        result = await store.client.query_points(
            settings.ingest_collection, query=points[0].vector, limit=1,
            query_filter=models.Filter(must=[store.attempt_filter(record), models.HasIdCondition(has_id=[point_id])]),
        )
        require(len(result.points) == 1 and str(result.points[0].id) == point_id
                and 0.999 <= result.points[0].score <= 1.001, "La búsqueda por el propio vector falló")
        print(json.dumps({"punto_id": point_id, "dimensiones": len(points[0].vector),
                          "similitud_consigo_mismo": result.points[0].score}, indent=2), flush=True)
    finally:
        await store.aclose()


async def ingest_blank_page(data):
    digest = hashlib.sha256(data).hexdigest()
    status, response = post(data)
    require(status == 200 and response.get("chunks_stored", 0) > 0, "La ingesta del PDF sintético falló")
    settings = Settings()
    ledger = IngestionLedger(settings.ingestion_ledger_path)
    record = ledger.find_by_content(digest)[-1]
    pages = ledger.pages(record.ingestion_id)
    require(len(pages) == 2 and pages[0] == PageRecord(0, False, 0)
            and pages[1].text_detected and pages[1].chunk_count > 0, "El registro de páginas no coincide")
    store = IngestionVectorStore(settings, ledger.identity(create=False))
    try:
        await store.ensure(create=False)
        await store.verify(record)
        points = await store.client.count(settings.ingest_collection, exact=True, count_filter=models.Filter(must=[
            store.attempt_filter(record), models.FieldCondition(key="page_number", match=models.MatchValue(value=0)),
        ]))
        require(points.count == 0, "La página sin texto tiene puntos en Qdrant")
    finally:
        await store.aclose()
    print("[OK] PDF sintético: página física 0 sin texto ni puntos; página 1 con fragmentos.")
    describe(ledger, record, response)


def snapshot():
    """Write a consistent SQLite backup to stdout, never copy a live WAL file."""
    path = Path(Settings().ingestion_ledger_path).absolute()
    with tempfile.TemporaryDirectory(prefix="visual-ledger-") as temporary:
        backup = Path(temporary) / "ledger.sqlite3"
        source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
            # A standalone snapshot should not require WAL/SHM sidecars when a
            # graphical viewer opens it on another machine or read-only path.
            mode = destination.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            require(mode.lower() == "delete", "No se pudo preparar la copia SQLite independiente")
        finally:
            destination.close()
            source.close()
        sys.stdout.buffer.write(backup.read_bytes())


def verify_snapshot(data):
    with tempfile.TemporaryDirectory(prefix="visual-ledger-check-") as temporary:
        path = Path(temporary) / "ledger.sqlite3"
        path.write_bytes(data)
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
            require(connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "La copia SQLite está dañada")
            require(connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete",
                    "La copia SQLite no es independiente de archivos WAL")
            completed = connection.execute("SELECT COUNT(*) FROM ingestions WHERE state='completed'").fetchone()[0]
            empty = connection.execute(
                "SELECT COUNT(*) FROM ingestion_pages WHERE text_detected=0 AND chunk_count=0"
            ).fetchone()[0]
            require(completed >= 3 and empty >= 1, "Faltan ingestas o páginas en la copia SQLite")
    print(f"[OK] Copia SQLite íntegra: {completed} ingestas completadas y {empty} páginas sin texto.")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {
        "pdf", "duplicado", "pdf-sintetico", "pagina-vacia", "snapshot", "verificar-snapshot",
    }:
        raise SystemExit("Uso: recorrido_visual.py pdf|duplicado|pdf-sintetico|pagina-vacia|snapshot|verificar-snapshot")
    if sys.argv[1] == "snapshot":
        snapshot()
    elif sys.argv[1] == "verificar-snapshot":
        verify_snapshot(sys.stdin.buffer.read())
    elif sys.argv[1] == "pdf-sintetico":
        sys.stdout.buffer.write(scanned_with_empty_first_page())
    elif sys.argv[1] == "pagina-vacia":
        asyncio.run(ingest_blank_page(sys.stdin.buffer.read()))
    else:
        ingest_sample(duplicate=sys.argv[1] == "duplicado")


if __name__ == "__main__":
    main()
