"""Durable, local ingestion metadata; never store PDF or OCR text here.

The ledger and Qdrant are independent systems. A ``cleanup_pending`` record
means that a write may have reached Qdrant; it does not claim rollback succeeded.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import Iterator, Sequence
from uuid import UUID

from app.core.local_storage import StorageError, file_lock, private_directory, private_file


_IDENTITY = "document-intelligence-ingestion-ledger"
_SCHEMA_VERSION = 2
_HEX_256 = re.compile(r"[0-9a-f]{64}\Z")
_ERROR_CODES = frozenset({
    "invalid_pdf", "no_text", "chunking_error", "chunk_limit", "ocr_unavailable", "ocr_timeout",
    "embedding_unavailable", "embedding_failed", "qdrant_unavailable", "qdrant_timeout",
    "cancelled", "internal_error", "interrupted", "cleanup_failed",
})


class LedgerError(RuntimeError):
    """The ingestion ledger is unavailable, incompatible, or in an invalid state."""


class LedgerFormatError(LedgerError):
    """The file is not an initialized ledger of a supported version."""


class LedgerStateError(LedgerError):
    """An attempt does not exist or its state does not allow the transition."""


@dataclass(frozen=True)
class PageRecord:
    page_number: int
    text_detected: bool
    chunk_count: int


@dataclass(frozen=True)
class IngestionRecord:
    ingestion_id: str
    document_id: str
    content_sha256: str
    processing_signature: str
    collection: str
    model_name: str
    model_revision: str
    chunk_tokens: int
    overlap_tokens: int
    endpoint_key: str
    state: str
    expected_chunks: int | None
    physical_pages: int | None
    write_uncertain: bool
    owner_id: str | None
    error_code: str | None
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("Expected a UUID") from None


def _digest(value: str) -> str:
    if not isinstance(value, str) or not _HEX_256.fullmatch(value):
        raise ValueError("Expected a lowercase SHA-256 digest")
    return value


def _label(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid ledger configuration label")
    return value


class IngestionLedger:
    """A SQLite ledger shared by processes on the same host and local volume."""

    def __init__(self, path: str | Path, *, timeout_seconds: float = 5.0):
        self.path = Path(path)
        if (str(path) == ":memory:" or type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("A persistent ledger path and positive timeout are required")
        self.timeout_seconds = timeout_seconds

    @contextmanager
    def lock(self, name: str, *, timeout: float = 0):
        """Same-host ownership; a process death releases the lock, not its record."""
        if name != "initialize" and not re.fullmatch(r"[a-z0-9_-]{1,80}", name):
            raise ValueError("Invalid lock name")
        try:
            private_directory(self.path.parent)
            with file_lock(self.path.parent / (self.path.name + "." + name + ".lock"), timeout=timeout):
                yield
        except StorageError as error:
            raise LedgerStateError(str(error)) from None

    def attempt_lock(self, ingestion_id: str):
        return self.lock("attempt-" + _uuid(ingestion_id))

    @contextmanager
    def _connect(self, *, create: bool = False) -> Iterator[sqlite3.Connection]:
        if not create and not self.path.is_file():
            raise LedgerFormatError("Ingestion ledger has not been initialized")
        connection = None
        try:
            private_directory(self.path.parent)
            fd, _ = private_file(self.path, create=False)
            os.close(fd)
            destination = self.path if create else self.path.absolute().as_uri() + "?mode=rw"
            connection = sqlite3.connect(
                destination, uri=not create, timeout=self.timeout_seconds, isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
        except (OSError, sqlite3.Error, StorageError):
            if connection is not None:
                connection.close()
            raise LedgerError("Could not open the ingestion ledger") from None
        try:
            yield connection
        except sqlite3.Error:
            raise LedgerError("Ingestion ledger operation failed") from None
        finally:
            connection.close()

    @contextmanager
    def _transaction(self, *, create: bool = False) -> Iterator[sqlite3.Connection]:
        with self._connect(create=create) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _verify(connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if version != _SCHEMA_VERSION or not {"ledger_metadata", "ingestions", "ingestion_pages"} <= tables:
            raise LedgerFormatError("Unsupported ingestion ledger format")
        row = connection.execute("SELECT value FROM ledger_metadata WHERE key='identity'").fetchone()
        if row is None or row[0] != _IDENTITY:
            raise LedgerFormatError("Unsupported ingestion ledger identity")

    def initialize(self) -> None:
        """Serialize creation and WAL setup across processes, not just threads."""
        with self.lock("initialize", timeout=self.timeout_seconds):
            self._initialize_locked()

    def _initialize_locked(self) -> None:
        try:
            fd, created = private_file(self.path, create=True)
            os.close(fd)
        except StorageError:
            raise LedgerError("Could not create a private ingestion ledger") from None
        if not created and self.path.stat().st_size == 0:
            raise LedgerFormatError("Refusing to initialize a pre-existing empty file")
        with self._transaction(create=True) as connection:
            objects = connection.execute(
                "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
            ).fetchone()
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if objects is not None or version != 0:
                self._verify(connection)
            else:
                connection.execute("CREATE TABLE ledger_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                connection.execute("INSERT INTO ledger_metadata VALUES ('identity', ?)", (_IDENTITY,))
                connection.execute("""
                    CREATE TABLE ingestions (
                        ingestion_id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL UNIQUE,
                        content_sha256 TEXT NOT NULL,
                        processing_signature TEXT NOT NULL,
                        collection TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        model_revision TEXT NOT NULL,
                        chunk_tokens INTEGER NOT NULL,
                        overlap_tokens INTEGER NOT NULL,
                        endpoint_key TEXT NOT NULL,
                        state TEXT NOT NULL CHECK (state IN (
                            'processing', 'writing', 'completed', 'failed', 'cleanup_pending', 'cleaned'
                        )),
                        expected_chunks INTEGER,
                        physical_pages INTEGER,
                        write_uncertain INTEGER NOT NULL DEFAULT 0,
                        owner_id TEXT,
                        error_code TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                connection.execute("CREATE INDEX ingestions_content_sha256 ON ingestions(content_sha256)")
                connection.execute("""
                    CREATE TABLE ingestion_pages (
                        ingestion_id TEXT NOT NULL REFERENCES ingestions(ingestion_id),
                        page_number INTEGER NOT NULL CHECK (page_number >= 0),
                        text_detected INTEGER NOT NULL CHECK (text_detected IN (0, 1)),
                        chunk_count INTEGER NOT NULL CHECK (chunk_count >= 0),
                        PRIMARY KEY (ingestion_id, page_number),
                        CHECK (text_detected = 1 OR chunk_count = 0)
                    )
                """)
                connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        with self._connect() as connection:
            mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode.lower() != "wal":
                raise LedgerError("Could not enable the ingestion ledger write-ahead log")

    def create(
        self, *, ingestion_id: str, document_id: str, content_sha256: str,
        processing_signature: str, collection: str, model_name: str,
        model_revision: str, chunk_tokens: int, overlap_tokens: int,
        owner_id: str | None = None,
        endpoint_key: str = "0" * 64,
    ) -> IngestionRecord:
        ingestion_id, document_id = _uuid(ingestion_id), _uuid(document_id)
        _digest(content_sha256)
        _digest(processing_signature)
        _digest(endpoint_key)
        _label(collection)
        _label(model_name)
        _label(model_revision)
        if (type(chunk_tokens) is not int or type(overlap_tokens) is not int
                or chunk_tokens <= 0 or not 0 <= overlap_tokens < chunk_tokens):
            raise ValueError("Invalid recorded chunk limits")
        now = _now()
        with self._transaction() as connection:
            self._verify(connection)
            if connection.execute(
                "SELECT 1 FROM ingestions WHERE ingestion_id=? OR document_id=?", (ingestion_id, document_id)
            ).fetchone():
                raise LedgerStateError("Ingestion or document ID already exists")
            connection.execute(
                """INSERT INTO ingestions VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'processing', NULL, NULL, 0, ?, NULL, ?, ?
                )""",
                (ingestion_id, document_id, content_sha256, processing_signature, collection,
                 model_name, model_revision, chunk_tokens, overlap_tokens, endpoint_key, owner_id, now, now),
            )
        return self.get(ingestion_id)

    def get(self, ingestion_id: str) -> IngestionRecord:
        with self._connect() as connection:
            self._verify(connection)
            row = connection.execute("SELECT * FROM ingestions WHERE ingestion_id=?", (_uuid(ingestion_id),)).fetchone()
            if row is None:
                raise LedgerStateError("Ingestion does not exist")
            return IngestionRecord(**dict(row))

    def find_by_content(self, content_sha256: str) -> list[IngestionRecord]:
        """Find attempts with identical input bytes; never merge or delete them."""
        with self._connect() as connection:
            self._verify(connection)
            rows = connection.execute(
                "SELECT * FROM ingestions WHERE content_sha256=? ORDER BY created_at, ingestion_id",
                (_digest(content_sha256),),
            ).fetchall()
            return [IngestionRecord(**dict(row)) for row in rows]

    def pending(self, *, limit: int = 100) -> list[IngestionRecord]:
        """Operational inventory, not evidence that an ingestion is abandoned."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Pending-record limit must be between 1 and 1000")
        with self._connect() as connection:
            self._verify(connection)
            rows = connection.execute(
                "SELECT * FROM ingestions WHERE state IN ('processing','writing','cleanup_pending') "
                "ORDER BY created_at, ingestion_id LIMIT ?", (limit,),
            ).fetchall()
            return [IngestionRecord(**dict(row)) for row in rows]

    def record_pages(self, ingestion_id: str, pages: Sequence[PageRecord], *, physical_pages: int) -> None:
        """Record every physical page exactly once, including empty OCR results."""
        ingestion_id = _uuid(ingestion_id)
        pages = tuple(pages)
        if type(physical_pages) is not int or len(pages) != physical_pages or not pages or any(
            not isinstance(page, PageRecord)
            or type(page.page_number) is not int or page.page_number != index
            or type(page.text_detected) is not bool
            or type(page.chunk_count) is not int or page.chunk_count < 0
            or (not page.text_detected and page.chunk_count != 0)
            for index, page in enumerate(pages)
        ):
            raise ValueError("Expected all physical pages in zero-based order with valid counts")
        with self._transaction() as connection:
            self._verify(connection)
            self._require_state(connection, ingestion_id, "processing")
            if connection.execute("SELECT 1 FROM ingestion_pages WHERE ingestion_id=?", (ingestion_id,)).fetchone():
                raise LedgerStateError("Pages have already been recorded")
            connection.executemany(
                "INSERT INTO ingestion_pages VALUES (?, ?, ?, ?)",
                [(ingestion_id, page.page_number, int(page.text_detected), page.chunk_count) for page in pages],
            )
            connection.execute(
                "UPDATE ingestions SET physical_pages=?, updated_at=? WHERE ingestion_id=?",
                (physical_pages, _now(), ingestion_id),
            )

    def pages(self, ingestion_id: str) -> list[PageRecord]:
        ingestion_id = _uuid(ingestion_id)
        with self._connect() as connection:
            self._verify(connection)
            if not connection.execute("SELECT 1 FROM ingestions WHERE ingestion_id=?", (ingestion_id,)).fetchone():
                raise LedgerStateError("Ingestion does not exist")
            rows = connection.execute(
                "SELECT page_number, text_detected, chunk_count FROM ingestion_pages "
                "WHERE ingestion_id=? ORDER BY page_number", (ingestion_id,),
            ).fetchall()
            return [PageRecord(row[0], bool(row[1]), row[2]) for row in rows]

    def set_chunk_counts(self, ingestion_id: str, counts: Sequence[int]) -> None:
        """Finalize preparation counts without removing/reindexing OCR pages."""
        current = self.pages(ingestion_id)
        if (len(current) != len(counts) or any(type(n) is not int or n < 0 for n in counts)
                or any(not page.text_detected and count for page, count in zip(current, counts))):
            raise LedgerStateError("Chunk counts do not match the physical pages")
        with self._transaction() as connection:
            self._verify(connection)
            self._require_state(connection, _uuid(ingestion_id), "processing")
            connection.executemany(
                "UPDATE ingestion_pages SET chunk_count=? WHERE ingestion_id=? AND page_number=?",
                [(count, ingestion_id, index) for index, count in enumerate(counts)],
            )

    @staticmethod
    def _require_state(connection: sqlite3.Connection, ingestion_id: str, state: str) -> None:
        row = connection.execute("SELECT state FROM ingestions WHERE ingestion_id=?", (ingestion_id,)).fetchone()
        if row is None or row[0] != state:
            raise LedgerStateError("Ingestion does not exist or is in an invalid state")

    def start_writing(self, ingestion_id: str) -> None:
        """Record write intent before submitting any Qdrant points."""
        ingestion_id = _uuid(ingestion_id)
        with self._transaction() as connection:
            self._verify(connection)
            self._require_state(connection, ingestion_id, "processing")
            rows = connection.execute(
                "SELECT text_detected, chunk_count FROM ingestion_pages WHERE ingestion_id=?", (ingestion_id,)
            ).fetchall()
            total = sum(row[1] for row in rows)
            if not rows or total == 0 or any(row[0] and row[1] == 0 for row in rows):
                raise LedgerStateError("Pages have not produced a complete, non-empty set of chunks")
            connection.execute(
                "UPDATE ingestions SET state='writing', expected_chunks=?, updated_at=? WHERE ingestion_id=?",
                (total, _now(), ingestion_id),
            )

    def complete(self, ingestion_id: str) -> None:
        """Call only after all intended Qdrant writes have been confirmed."""
        ingestion_id = _uuid(ingestion_id)
        with self._transaction() as connection:
            self._verify(connection)
            self._require_state(connection, ingestion_id, "writing")
            if connection.execute("SELECT write_uncertain FROM ingestions WHERE ingestion_id=?", (ingestion_id,)).fetchone()[0]:
                raise LedgerStateError("A Qdrant write still has an unknown outcome")
            connection.execute(
                "UPDATE ingestions SET state='completed', owner_id=NULL, updated_at=? WHERE ingestion_id=?", (_now(), ingestion_id)
            )

    def fail(self, ingestion_id: str, error_code: str) -> None:
        """Record a safe error code; a started write may require later cleanup."""
        ingestion_id = _uuid(ingestion_id)
        if not isinstance(error_code, str) or error_code not in _ERROR_CODES:
            raise ValueError("Expected a non-sensitive error code")
        with self._transaction() as connection:
            self._verify(connection)
            row = connection.execute("SELECT state FROM ingestions WHERE ingestion_id=?", (ingestion_id,)).fetchone()
            if row is None or row[0] not in {"processing", "writing"}:
                raise LedgerStateError("Ingestion does not exist or cannot fail from its current state")
            state = "cleanup_pending" if row[0] == "writing" else "failed"
            connection.execute(
                "UPDATE ingestions SET state=?, error_code=?, owner_id=NULL, updated_at=? WHERE ingestion_id=?",
                (state, error_code, _now(), ingestion_id),
            )

    def write_intent(self, ingestion_id: str) -> None:
        """Persist uncertainty BEFORE a remote mutation; timeout must not clear it."""
        self._write_status(ingestion_id, True)

    def write_confirmed(self, ingestion_id: str) -> None:
        self._write_status(ingestion_id, False)

    def _write_status(self, ingestion_id: str, uncertain: bool) -> None:
        with self._transaction() as connection:
            self._verify(connection)
            self._require_state(connection, _uuid(ingestion_id), "writing")
            connection.execute(
                "UPDATE ingestions SET write_uncertain=?, updated_at=? WHERE ingestion_id=?",
                (int(uncertain), _now(), ingestion_id),
            )

    def recover(self, ingestion_id: str) -> IngestionRecord:
        """Caller MUST hold attempt_lock; never infer inactivity just from age."""
        record = self.get(ingestion_id)
        if record.state in {"processing", "writing"}:
            self.fail(ingestion_id, "interrupted")
        return self.get(ingestion_id)

    def mark_cleaned(self, ingestion_id: str) -> None:
        """Caller holds attempt_lock and has verified scoped point absence."""
        with self._transaction() as connection:
            self._verify(connection)
            self._require_state(connection, _uuid(ingestion_id), "cleanup_pending")
            connection.execute(
                "UPDATE ingestions SET state='cleaned', write_uncertain=0, owner_id=NULL, updated_at=? WHERE ingestion_id=?",
                (_now(), ingestion_id),
            )

    def identity(self, *, create: bool = True) -> str:
        with self._transaction() as connection:
            self._verify(connection)
            row = connection.execute("SELECT value FROM ledger_metadata WHERE key='ledger_id'").fetchone()
            if row:
                return row[0]
            if not create:
                raise LedgerFormatError("The ingestion ledger has no recorded identity")
            from uuid import uuid4
            value = str(uuid4())
            connection.execute("INSERT INTO ledger_metadata VALUES ('ledger_id', ?)", (value,))
            return value
