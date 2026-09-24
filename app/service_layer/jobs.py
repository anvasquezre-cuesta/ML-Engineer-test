"""Use cases of asynchronous jobs: submit one, and process a delivery.

The worker is the only authority on a job's state. Every transition is a
conditional write, so concurrent deliveries of the same job run it once.
"""

from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Sequence
import dataclasses
import datetime
import hashlib
import json
import uuid

import structlog

from app.domain import errors
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
TERMINAL = frozenset({jobs.JobStatus.SUCCEEDED, jobs.JobStatus.DEAD_LETTERED})

log = structlog.stdlib.get_logger(__name__)


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
        """
        content_hash = hashlib.sha256(pdf).hexdigest()
        key = document_key or filename or f"sha256:{content_hash}"
        job_id = str(uuid.uuid4())
        input_key = f"inputs/{job_id}.pdf"
        await self._blobs.put(input_key, pdf)
        order = None
        if kind is jobs.JobKind.EXTRACT:
            order = await self._writer.allocate_order(key)
        now = self._clock()
        job = jobs.Job(
            job_id=job_id,
            kind=kind,
            status=jobs.JobStatus.QUEUED,
            input_key=input_key,
            attempts=0,
            max_attempts=self._max_attempts,
            created_at=now,
            updated_at=now,
            document_key=key,
            content_hash=content_hash,
            order=order,
            names=tuple(names),
        )
        await self._repository.create(job)
        await self._queue.publish(jobs.JobMessage(job_id, kind))
        return job


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
        """
        job_id = delivery.message.job_id
        job = await self._repository.get(job_id)
        lease = self._clock() + datetime.timedelta(seconds=self._lease_s)
        claimed = None
        if job is not None and job.status not in TERMINAL:
            claimed = await self._repository.claim(job_id, lease)
        if claimed is None:
            await delivery.ack()
            return
        try:
            result_key = await self._run(claimed)
        except errors.AppError as exc:
            await self._fail(claimed, delivery, exc.code, exc.detail, exc)
            return
        except Exception as exc:
            log.exception("job.unexpected_error", job_id=job_id)
            unexpected = errors.UnexpectedError()
            await self._fail(
                claimed, delivery, unexpected.code, unexpected.detail, exc
            )
            return
        await self._repository.mark_succeeded(job_id, result_key)
        await delivery.ack()
        log.info("job.succeeded", job_id=job_id, attempts=claimed.attempts)

    async def _run(self, job: jobs.Job) -> str:
        """Runs the job's work and stores its result.

        Args:
            job: The claimed job.

        Returns:
            Blob key of the result.

        Raises:
            errors.JobInputMissingError: If the staged PDF is gone.
        """
        pdf = await self._blobs.get(job.input_key)
        if pdf is None or job.document_key is None:
            raise errors.JobInputMissingError()
        if job.kind is jobs.JobKind.EXTRACT:
            if job.content_hash is None or job.order is None:
                raise errors.JobInputMissingError()
            extracted = await self._extract(pdf, job.names)
            await self._record(
                job.document_key,
                job.content_hash,
                job.order,
                extracted.occurrences,
                "job",
                job.job_id,
            )
            result: object = extracted
        else:
            result = await self._ingest(pdf, job.document_key)
        key = f"results/{job.job_id}.json"
        payload = json.dumps(dataclasses.asdict(result))  # type: ignore[call-overload]
        await self._blobs.put(key, payload.encode())
        return key

    async def _fail(
        self,
        job: jobs.Job,
        delivery: job_queue.Delivery,
        code: str,
        message: str,
        exc: Exception,
    ) -> None:
        """Retries a transient failure or dead-letters the job.

        The store is updated before the delivery is settled, so a job is
        never in the dead-letter queue while its record says otherwise.

        Args:
            job: The claimed job, with this attempt counted.
            delivery: The received message.
            code: Error code to record.
            message: Safe error message to record.
            exc: The failure.
        """
        retryable = isinstance(exc, errors.AppError) and exc.retryable
        if retryable and job.attempts < job.max_attempts:
            await self._repository.mark_retrying(job.job_id, code, message)
            delay = self._retry_delay_s * 2 ** (job.attempts - 1)
            await delivery.retry(delay)
            log.warning(
                "job.retrying", job_id=job.job_id, code=code, delay_s=delay
            )
            return
        await self._repository.mark_dead_lettered(job.job_id, code, message)
        await delivery.dead_letter()
        log.warning(
            "job.dead_lettered",
            job_id=job.job_id,
            code=code,
            attempts=job.attempts,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class ReapReport:
    """What one reaper pass did.

    Attributes:
        requeued: Jobs with a lapsed lease sent back to a worker.
        dead_lettered: Jobs with a lapsed lease and no attempts left.
        republished: Jobs stuck in ``queued`` published again.
    """

    requeued: int
    dead_lettered: int
    republished: int


class ReapJobs:
    """Recovers jobs whose worker died or whose message was lost."""

    def __init__(
        self,
        repository: job_repository.JobRepository,
        queue: job_queue.JobQueue,
        clock: Clock,
        queued_stale_s: float,
        limit: int,
    ) -> None:
        """Initializes the use case.

        Args:
            repository: The job store.
            queue: Delivers recovered jobs again.
            clock: Returns the current time (UTC).
            queued_stale_s: Age after which a queued job is republished.
            limit: Most queued jobs inspected per pass.
        """
        self._repository = repository
        self._queue = queue
        self._clock = clock
        self._queued_stale_s = queued_stale_s
        self._limit = limit

    async def __call__(self) -> ReapReport:
        """Runs one pass over lapsed leases and stale queued jobs.

        A running job whose lease lapsed goes back to ``retrying`` and is
        published again, or is dead-lettered when its attempts are used up.
        A job still ``queued`` after ``queued_stale_s`` is published again;
        a duplicate message is harmless because claims are conditional.

        Returns:
            What the pass did.
        """
        now = self._clock()
        lapsed = errors.JobLeaseExpiredError()
        requeued = dead_lettered = republished = 0
        for job in await self._repository.list_expired_leases(now):
            if job.attempts < job.max_attempts:
                moved = await self._repository.mark_retrying(
                    job.job_id, lapsed.code, lapsed.detail
                )
                if moved is not None:
                    message = jobs.JobMessage(job.job_id, job.kind)
                    await self._queue.publish(message)
                    requeued += 1
            elif await self._repository.mark_dead_lettered(
                job.job_id, lapsed.code, lapsed.detail
            ):
                dead_lettered += 1
        stale = now - datetime.timedelta(seconds=self._queued_stale_s)
        queued = await self._repository.list_by_status(
            jobs.JobStatus.QUEUED, self._limit
        )
        for job in queued:
            if job.created_at < stale:
                await self._queue.publish(jobs.JobMessage(job.job_id, job.kind))
                republished += 1
        report = ReapReport(requeued, dead_lettered, republished)
        if requeued or dead_lettered or republished:
            log.warning("jobs.reaped", **dataclasses.asdict(report))
        return report
