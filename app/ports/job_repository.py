"""Port for the durable record of every job."""

import abc
import datetime

from app.domain import jobs


class JobRepository(abc.ABC):
    """Job store whose transitions are atomic compare-and-set updates.

    A transition returns the updated job, or ``None`` when the job is not in
    the state the transition requires, so concurrent workers cannot both
    win. Every method may raise ``JobStoreUnavailableError``.
    """

    @abc.abstractmethod
    async def create(self, job: jobs.Job) -> None:
        """Stores a new job.

        Args:
            job: The job, normally in the ``queued`` state.
        """

    @abc.abstractmethod
    async def get(self, job_id: str) -> jobs.Job | None:
        """Reads one job.

        Args:
            job_id: Id of the job.

        Returns:
            The job, or ``None`` if it does not exist.
        """

    @abc.abstractmethod
    async def list_by_status(
        self, status: jobs.JobStatus, limit: int
    ) -> list[jobs.Job]:
        """Lists jobs in one state, most recently updated first.

        Args:
            status: State to filter by.
            limit: Maximum number of jobs to return.

        Returns:
            The matching jobs.
        """

    @abc.abstractmethod
    async def claim(
        self, job_id: str, lease_expires_at: datetime.datetime
    ) -> jobs.Job | None:
        """Moves a ``queued`` or ``retrying`` job to ``running``.

        Increments ``attempts`` and sets the lease.

        Args:
            job_id: Id of the job.
            lease_expires_at: When the new lease lapses (UTC).

        Returns:
            The claimed job, or ``None`` if it was not claimable.
        """

    @abc.abstractmethod
    async def mark_succeeded(
        self, job_id: str, result_key: str
    ) -> jobs.Job | None:
        """Moves a ``running`` job to ``succeeded``.

        Args:
            job_id: Id of the job.
            result_key: Blob key of the stored result.

        Returns:
            The updated job, or ``None`` if it was not running.
        """

    @abc.abstractmethod
    async def mark_retrying(
        self, job_id: str, error_code: str, error_message: str
    ) -> jobs.Job | None:
        """Moves a ``running`` job to ``retrying`` after a transient error.

        Args:
            job_id: Id of the job.
            error_code: Code of the failure.
            error_message: Safe message of the failure.

        Returns:
            The updated job, or ``None`` if it was not running.
        """

    @abc.abstractmethod
    async def mark_dead_lettered(
        self, job_id: str, error_code: str, error_message: str
    ) -> jobs.Job | None:
        """Moves a job that is not yet terminal to ``dead_lettered``.

        Args:
            job_id: Id of the job.
            error_code: Code of the final failure.
            error_message: Safe message of the final failure.

        Returns:
            The updated job, or ``None`` if it was already terminal.
        """

    @abc.abstractmethod
    async def list_expired_leases(
        self, now: datetime.datetime
    ) -> list[jobs.Job]:
        """Lists ``running`` jobs whose lease lapsed before ``now``.

        Args:
            now: The current time (UTC).

        Returns:
            Jobs whose worker is presumed dead.
        """
