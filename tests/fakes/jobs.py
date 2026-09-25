"""In-memory job store, blob store, queue and delivery."""

from collections.abc import AsyncIterator
import dataclasses
import datetime

from app.domain import jobs
from app.ports import blob_store
from app.ports import job_queue
from app.ports import job_repository


class InMemoryJobRepository(job_repository.JobRepository):
    """Job store whose transitions are compare-and-set on a dict."""

    def __init__(self) -> None:
        """Initializes an empty store."""
        self.jobs: dict[str, jobs.Job] = {}

    async def create(self, job: jobs.Job) -> None:
        """Stores a new job."""
        self.jobs[job.job_id] = job

    async def get(self, job_id: str) -> jobs.Job | None:
        """Reads one job."""
        return self.jobs.get(job_id)

    async def list_by_status(
        self, status: jobs.JobStatus, limit: int
    ) -> list[jobs.Job]:
        """Lists jobs in one state, most recently updated first."""
        found = [j for j in self.jobs.values() if j.status is status]
        found.sort(key=lambda j: j.updated_at, reverse=True)
        return found[:limit]

    async def claim(
        self, job_id: str, lease_expires_at: datetime.datetime
    ) -> jobs.Job | None:
        """Moves a waiting job to running and counts the attempt."""
        waiting = {jobs.JobStatus.QUEUED, jobs.JobStatus.RETRYING}
        return self._move(
            job_id,
            waiting,
            status=jobs.JobStatus.RUNNING,
            lease_expires_at=lease_expires_at,
            increment=True,
        )

    async def mark_succeeded(
        self, job_id: str, result_key: str
    ) -> jobs.Job | None:
        """Moves a running job to succeeded."""
        return self._move(
            job_id,
            {jobs.JobStatus.RUNNING},
            status=jobs.JobStatus.SUCCEEDED,
            result_key=result_key,
        )

    async def mark_retrying(
        self, job_id: str, error_code: str, error_message: str
    ) -> jobs.Job | None:
        """Moves a running job to retrying."""
        return self._move(
            job_id,
            {jobs.JobStatus.RUNNING},
            status=jobs.JobStatus.RETRYING,
            last_error_code=error_code,
            last_error_message=error_message,
        )

    async def mark_dead_lettered(
        self, job_id: str, error_code: str, error_message: str
    ) -> jobs.Job | None:
        """Moves a job that is not terminal to dead-lettered."""
        return self._move(
            job_id,
            {
                jobs.JobStatus.QUEUED,
                jobs.JobStatus.RUNNING,
                jobs.JobStatus.RETRYING,
            },
            status=jobs.JobStatus.DEAD_LETTERED,
            last_error_code=error_code,
            last_error_message=error_message,
        )

    async def list_expired_leases(
        self, now: datetime.datetime
    ) -> list[jobs.Job]:
        """Lists running jobs whose lease lapsed."""
        return [
            j
            for j in self.jobs.values()
            if j.status is jobs.JobStatus.RUNNING
            and j.lease_expires_at is not None
            and j.lease_expires_at < now
        ]

    def _move(
        self,
        job_id: str,
        allowed: set[jobs.JobStatus],
        increment: bool = False,
        **changes: object,
    ) -> jobs.Job | None:
        """Applies ``changes`` only if the job is in an allowed state."""
        job = self.jobs.get(job_id)
        if job is None or job.status not in allowed:
            return None
        attempts = job.attempts + 1 if increment else job.attempts
        updated = dataclasses.replace(job, attempts=attempts, **changes)  # type: ignore[arg-type]
        self.jobs[job_id] = updated
        return updated


class InMemoryBlobStore(blob_store.BlobStore):
    """Blob store on a dict."""

    def __init__(self) -> None:
        """Initializes an empty store."""
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        """Stores an object."""
        self.objects[key] = data

    async def get(self, key: str) -> bytes | None:
        """Reads an object."""
        return self.objects.get(key)

    async def delete(self, key: str) -> None:
        """Deletes an object."""
        self.objects.pop(key, None)


class RecordingJobQueue(job_queue.JobQueue):
    """Queue that records what is published.

    Attributes:
        published: Every published message, in order.
    """

    def __init__(self) -> None:
        """Initializes an empty queue."""
        self.published: list[jobs.JobMessage] = []

    async def publish(self, message: jobs.JobMessage) -> None:
        """Records the message."""
        self.published.append(message)

    async def consume(self) -> AsyncIterator[job_queue.Delivery]:
        """Yields nothing; tests deliver published messages themselves."""
        for _ in ():
            yield _


class RecordingDelivery(job_queue.Delivery):
    """Delivery that records how it was settled.

    Attributes:
        settled: ``ack``, ``retry:{delay}`` or ``dead_letter:{state}``,
            where ``state`` is the job's stored state at that moment.
    """

    def __init__(
        self, message: jobs.JobMessage, repository: InMemoryJobRepository
    ) -> None:
        """Initializes the delivery."""
        self.message = message
        self._repository = repository
        self.settled: list[str] = []

    async def ack(self) -> None:
        """Records an ack."""
        self.settled.append("ack")

    async def retry(self, delay_s: float) -> None:
        """Records a retry."""
        self.settled.append(f"retry:{delay_s:g}")

    async def dead_letter(self) -> None:
        """Records a dead-letter with the job's stored state."""
        job = self._repository.jobs.get(self.message.job_id)
        self.settled.append(f"dead_letter:{job.status if job else None}")
