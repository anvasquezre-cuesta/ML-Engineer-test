"""Use case: record every name occurrence of a document version."""

from collections.abc import Sequence

from app.domain import extraction
from app.domain import occurrences
from app.ports import occurrence_store


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

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError
