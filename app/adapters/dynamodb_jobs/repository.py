"""Job repository on DynamoDB; every transition is a conditional update.

One item per job under ``JOB#{job id}``. A status index keyed by status and
update time lists jobs in one state, most recently updated first.
"""

import datetime
from typing import Any

from app.domain import jobs
from app.ports import job_repository


class DynamoDbJobRepository(job_repository.JobRepository):
    """Job store whose state changes are compare-and-set updates."""

    def __init__(self, client: Any, table: str) -> None:
        """Initializes the repository.

        Args:
            client: The boto3 DynamoDB client.
            table: Table name.
        """
        self._client = client
        self._table = table

    async def ensure_table(self) -> None:
        """Creates the table and its status index if they are missing.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def create(self, job: jobs.Job) -> None:
        """Stores a new job.

        Args:
            job: The job.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def get(self, job_id: str) -> jobs.Job | None:
        """Reads one job, consistently.

        Args:
            job_id: Id of the job.

        Returns:
            The job, if any.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def list_by_status(
        self, status: jobs.JobStatus, limit: int
    ) -> list[jobs.Job]:
        """Lists jobs in one state, most recently updated first.

        Args:
            status: The state.
            limit: Most jobs to return.

        Returns:
            The jobs.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def claim(
        self, job_id: str, lease_expires_at: datetime.datetime
    ) -> jobs.Job | None:
        """Moves a queued or retrying job to running, counting the attempt.

        Args:
            job_id: Id of the job.
            lease_expires_at: When the lease lapses (UTC).

        Returns:
            The claimed job, or ``None`` if it was not claimable.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def mark_succeeded(
        self, job_id: str, result_key: str
    ) -> jobs.Job | None:
        """Moves a running job to succeeded.

        Args:
            job_id: Id of the job.
            result_key: Blob key of the result.

        Returns:
            The job, or ``None`` if it was not running.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def mark_retrying(
        self, job_id: str, error_code: str, error_message: str
    ) -> jobs.Job | None:
        """Moves a running job to retrying.

        Args:
            job_id: Id of the job.
            error_code: Code of the failure.
            error_message: Safe message of the failure.

        Returns:
            The job, or ``None`` if it was not running.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def mark_dead_lettered(
        self, job_id: str, error_code: str, error_message: str
    ) -> jobs.Job | None:
        """Moves a job that is not terminal to dead-lettered.

        Args:
            job_id: Id of the job.
            error_code: Code of the final failure.
            error_message: Safe message of the final failure.

        Returns:
            The job, or ``None`` if it was already terminal.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError

    async def list_expired_leases(
        self, now: datetime.datetime
    ) -> list[jobs.Job]:
        """Lists running jobs whose lease lapsed before ``now``.

        Args:
            now: The current time (UTC).

        Returns:
            The jobs.

        Raises:
            NotImplementedError: Always; not built yet.
        """
        raise NotImplementedError
