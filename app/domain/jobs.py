"""Value objects of asynchronous extraction and ingestion jobs."""

import dataclasses
import datetime
import enum

from app.domain import extraction


class JobKind(enum.StrEnum):
    """Work a job performs."""

    EXTRACT = "extract"
    INGEST = "ingest"


class JobStatus(enum.StrEnum):
    """Lifecycle state of a job.

    ``queued`` and ``retrying`` wait for a worker, ``running`` is leased by
    one, and ``succeeded`` and ``dead_lettered`` are terminal.
    """

    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    DEAD_LETTERED = "dead_lettered"


@dataclasses.dataclass(frozen=True, slots=True)
class Job:
    """The durable record of one job, owned by the worker.

    Attributes:
        job_id: Unique id of the job.
        kind: Work the job performs.
        status: Current lifecycle state.
        input_key: Blob key of the staged PDF.
        attempts: Number of times a worker has started the job.
        max_attempts: Attempts allowed before the job is dead-lettered.
        created_at: When the job was submitted (UTC).
        updated_at: When the record last changed (UTC).
        document_key: Identity of the document.
        content_hash: SHA-256 of the staged PDF.
        order: Occurrence acceptance order reserved at submission, for
            extraction jobs.
        names: Names to match against, for extraction jobs.
        lease_expires_at: When a running job's lease lapses (UTC).
        last_error_code: Code of the most recent failure.
        last_error_message: Safe message of the most recent failure.
        result_key: Blob key of the result once the job succeeded.
    """

    job_id: str
    kind: JobKind
    status: JobStatus
    input_key: str
    attempts: int
    max_attempts: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    document_key: str | None = None
    content_hash: str | None = None
    order: int | None = None
    names: tuple[extraction.QueryName, ...] = ()
    lease_expires_at: datetime.datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    result_key: str | None = None

    @property
    def dead_lettered(self) -> bool:
        """Returns whether the job has been given up on.

        Returns:
            ``True`` if the job is in the ``dead_lettered`` state.
        """
        return self.status is JobStatus.DEAD_LETTERED


@dataclasses.dataclass(frozen=True, slots=True)
class JobMessage:
    """The message that tells a worker to run a job.

    Attributes:
        job_id: Id of the job to run.
        kind: Work the job performs.
    """

    job_id: str
    kind: JobKind
