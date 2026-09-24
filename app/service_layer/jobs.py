"""Use cases of asynchronous jobs: submit one, and process a delivery.

The worker is the only authority on a job's state. Every transition is a
conditional write, so concurrent deliveries of the same job run it once.
"""

from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Sequence
import datetime

from app.domain import extraction
from app.domain import jobs
from app.domain import rag
from app.ports import blob_store
from app.ports import job_queue
from app.ports import job_repository
from app.ports import occurrence_store
from app.service_layer import occurrences

Extract = Callable[
    [bytes, Sequence[extraction.QueryName]],
    Awaitable[extraction.ExtractionResult],
]
Ingest = Callable[[bytes, str], Awaitable[rag.IngestResult]]
Clock = Callable[[], datetime.datetime]


class SubmitJob:
    """Stages a PDF, records a queued job and publishes it."""

    def __init__(
        self,
        blobs: blob_store.BlobStore,
        repository: job_repository.JobRepository,
        queue: job_queue.JobQueue,
        writer: occurrence_store.OccurrenceWriter,
        max_attempts: int,
        clock: Clock,
    ) -> None:
        """Initializes the use case.

        Args:
            blobs: Stores the staged PDF.
            repository: Records the job.
            queue: Delivers the job to a worker.
            writer: Reserves the occurrence order of extraction jobs.
            max_attempts: Attempts before the job is dead-lettered.
            clock: Returns the current time (UTC).
        """
        self._blobs = blobs
        self._repository = repository
        self._queue = queue
        self._writer = writer
        self._max_attempts = max_attempts
        self._clock = clock

    async def __call__(
        self,
        kind: jobs.JobKind,
        pdf: bytes,
        document_key: str | None,
        filename: str | None,
        names: Sequence[extraction.QueryName] = (),
    ) -> jobs.Job:
        """Submits a job for ``pdf``.

        The document key is ``document_key``, else the filename, else
        ``sha256:{content hash}``. Extraction jobs reserve their occurrence
        order now, so a job that runs late cannot replace a newer version.

        Args:
            kind: Extract or ingest.
            pdf: The validated PDF content.
            document_key: Key chosen by the caller, if any.
            filename: Name of the uploaded file, if any.
            names: Names to match against, for extraction jobs.

        Returns:
            The queued job.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError


class ProcessJob:
    """Runs one delivered job and settles its delivery."""

    def __init__(
        self,
        repository: job_repository.JobRepository,
        blobs: blob_store.BlobStore,
        extract: Extract,
        record: occurrences.RecordOccurrences,
        ingest: Ingest,
        clock: Clock,
        lease_s: float,
        retry_delay_s: float,
    ) -> None:
        """Initializes the use case.

        Args:
            repository: The job store.
            blobs: Holds staged PDFs and results.
            extract: Finds and matches the names of a PDF.
            record: Stores an extraction's occurrences.
            ingest: Indexes a PDF for questions.
            clock: Returns the current time (UTC).
            lease_s: Seconds a claimed job belongs to this worker.
            retry_delay_s: Backoff before the first retry; it doubles.
        """
        self._repository = repository
        self._blobs = blobs
        self._extract = extract
        self._record = record
        self._ingest = ingest
        self._clock = clock
        self._lease_s = lease_s
        self._retry_delay_s = retry_delay_s

    async def __call__(self, delivery: job_queue.Delivery) -> None:
        """Runs the delivered job once and settles the delivery.

        A job that is finished, unknown or running elsewhere is acked
        without running. A retryable failure is retried with a doubling
        backoff until the attempts run out; any other failure dead-letters
        the job at once. The store is updated before the delivery is
        settled.

        Args:
            delivery: The received message.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError
