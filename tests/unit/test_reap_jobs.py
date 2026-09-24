"""Reaper: jobs of dead workers and lost messages are recovered."""

import dataclasses
import datetime

from app.domain import jobs
from app.service_layer import jobs as job_service
from tests.fakes import jobs as job_fakes

NOW = datetime.datetime(2026, 9, 24, 12, tzinfo=datetime.UTC)
BASE = jobs.Job(
    job_id="",
    kind=jobs.JobKind.EXTRACT,
    status=jobs.JobStatus.RUNNING,
    input_key="inputs/x.pdf",
    attempts=1,
    max_attempts=3,
    created_at=NOW,
    updated_at=NOW,
)


def ago(seconds: float) -> datetime.datetime:
    """Returns the time ``seconds`` before ``NOW``.

    Args:
        seconds: How long ago.

    Returns:
        The time.
    """
    return NOW - datetime.timedelta(seconds=seconds)


async def reap(
    *stored: jobs.Job,
) -> tuple[job_fakes.InMemoryJobRepository, job_fakes.RecordingJobQueue]:
    """Runs one reaper pass over ``stored`` jobs.

    Args:
        *stored: The jobs in the store.

    Returns:
        The store and the queue afterwards.
    """
    repository = job_fakes.InMemoryJobRepository()
    queue = job_fakes.RecordingJobQueue()
    for job in stored:
        await repository.create(job)
    reaper = job_service.ReapJobs(
        repository, queue, lambda: NOW, queued_stale_s=120, limit=10
    )
    await reaper()
    return repository, queue


async def test_lapsed_leases_are_retried_until_attempts_run_out() -> None:
    repository, queue = await reap(
        dataclasses.replace(BASE, job_id="crashed", lease_expires_at=ago(5)),
        dataclasses.replace(
            BASE, job_id="exhausted", attempts=3, lease_expires_at=ago(5)
        ),
    )

    assert {k: j.status for k, j in repository.jobs.items()} == {
        "crashed": jobs.JobStatus.RETRYING,
        "exhausted": jobs.JobStatus.DEAD_LETTERED,
    }
    assert repository.jobs["exhausted"].last_error_code == "job.lease_expired"
    assert [m.job_id for m in queue.published] == ["crashed"]


async def test_only_stale_queued_jobs_are_published_again() -> None:
    queued = dataclasses.replace(BASE, status=jobs.JobStatus.QUEUED)
    repository, queue = await reap(
        dataclasses.replace(queued, job_id="lost", created_at=ago(600)),
        dataclasses.replace(queued, job_id="fresh", created_at=ago(5)),
    )

    assert [m.job_id for m in queue.published] == ["lost"]
    assert repository.jobs["lost"].status is jobs.JobStatus.QUEUED
