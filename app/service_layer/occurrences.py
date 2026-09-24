"""Use cases: record every name occurrence of a document, and query them."""

from collections.abc import AsyncIterator
from collections.abc import Sequence
import uuid

import structlog

from app.domain import errors
from app.domain import extraction
from app.domain import ids
from app.domain import normalize
from app.domain import occurrences
from app.ports import occurrence_store

log = structlog.stdlib.get_logger(__name__)


class RecordOccurrences:
    """Stores one extraction run as a new generation and promotes it."""

    def __init__(
        self, writer: occurrence_store.OccurrenceWriter, extractor: str
    ) -> None:
        """Initializes the use case.

        Args:
            writer: The occurrence store.
            extractor: Fingerprint of the models and settings in use.
        """
        self._writer = writer
        self._extractor = extractor

    async def __call__(
        self,
        document_key: str,
        content_hash: str,
        order: int,
        found: Sequence[extraction.NameOccurrence],
        source: occurrences.Source,
        job_id: str | None = None,
    ) -> occurrences.RecordOutcome:
        """Records the occurrences one run found in one document version.

        Nothing is written when the same content, extractor and an equal or
        higher order are already current. Otherwise a new generation is
        written, sealed and promoted; it stays in history when a higher
        order is already current.

        Args:
            document_key: The document.
            content_hash: SHA-256 of the document content.
            order: Acceptance order from ``allocate_order``.
            found: The occurrences, in page order.
            source: ``sync`` or ``job``.
            job_id: The job that ran the extraction, if any.

        Returns:
            Whether the run was recorded, unchanged or superseded.
        """
        current = (await self._writer.head(document_key)).manifest
        if (
            current is not None
            and current.content_hash == content_hash
            and current.extractor == self._extractor
        ):
            return occurrences.RecordOutcome.UNCHANGED
        generation = str(uuid.uuid4())
        items = [
            occurrences.StoredOccurrence(
                occurrence_id=ids.occurrence_id(
                    document_key,
                    content_hash,
                    generation,
                    occurrence.page_number,
                    ordinal,
                ),
                document_key=document_key,
                content_hash=content_hash,
                generation=generation,
                ordinal=ordinal,
                name=occurrence.name,
                normalized_name=normalize.normalize_name(occurrence.name),
                page_number=occurrence.page_number,
                box=occurrence.box,
            )
            for ordinal, occurrence in enumerate(found)
        ]
        manifest = occurrences.GenerationManifest(
            document_key=document_key,
            generation=generation,
            order=order,
            content_hash=content_hash,
            extractor=self._extractor,
            occurrence_count=len(items),
            source=source,
            job_id=job_id,
        )
        await self._writer.write_generation(manifest, items)
        promoted = await self._writer.promote(manifest)
        log.info(
            "occurrences.recorded",
            document_id=ids.document_id(document_key),
            generation=generation,
            order=order,
            occurrences=len(items),
            outcome=str(promoted),
        )
        if promoted == occurrences.PromoteOutcome.SUPERSEDED:
            return occurrences.RecordOutcome.SUPERSEDED
        return occurrences.RecordOutcome.RECORDED


class QueryOccurrences:
    """Streams the current occurrences, optionally filtered."""

    def __init__(self, reader: occurrence_store.OccurrenceReader) -> None:
        """Initializes the use case.

        Args:
            reader: The occurrence store.
        """
        self._reader = reader

    async def __call__(
        self, document_key: str | None = None, name: str | None = None
    ) -> AsyncIterator[occurrences.StoredOccurrence]:
        """Streams every current occurrence matching the filters.

        Each document is read at one generation and must return exactly the
        count its seal recorded; documents are not read at one instant.

        Args:
            document_key: Only this document, if given.
            name: Only names containing it, ignoring case and accents.

        Yields:
            The occurrences, document by document, in ordinal order.

        Raises:
            errors.OccurrenceIntegrityError: If a version returns a different
                number of occurrences than its seal recorded.
        """
        wanted = normalize.normalize_name(name) if name else None
        async for head in self._reader.documents():
            manifest = head.manifest
            skipped = document_key not in (None, head.document_key)
            if manifest is None or skipped:
                continue
            rows = [row async for row in self._reader.current(head)]
            if len(rows) != manifest.occurrence_count:
                raise errors.OccurrenceIntegrityError(
                    f"Generation {manifest.generation} returned {len(rows)} "
                    f"of {manifest.occurrence_count} occurrences."
                )
            for row in rows:
                if wanted is None or wanted in row.normalized_name:
                    yield row
