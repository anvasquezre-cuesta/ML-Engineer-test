"""The fake and DynamoDB Local honour the same job repository contract."""

import asyncio
from collections.abc import AsyncIterator
import contextlib
import datetime
import uuid

import pydantic
import pytest

from app import config
from app.adapters.dynamodb_jobs import repository as dynamodb_jobs
from app.adapters.dynamodb_occurrences import store as dynamodb_store
from app.domain import extraction
from app.domain import jobs
from tests.fakes import jobs as job_fakes

Repository = (
    job_fakes.InMemoryJobRepository | dynamodb_jobs.DynamoDbJobRepository
)
NOW = datetime.datetime(2026, 9, 24, 12, tzinfo=datetime.UTC)
KINDS = [
    "fake",
    pytest.param(
        "dynamodb",
        marks=[
            pytest.mark.docker,
            pytest.mark.xfail(
                strict=True, raises=NotImplementedError, reason="not built"
            ),
        ],
    ),
]


@contextlib.asynccontextmanager
async def repository_of(kind: str) -> AsyncIterator[Repository]:
    """Opens an empty job store; DynamoDB Local gets a table of its own.

    Args:
        kind: ``fake`` or ``dynamodb``.

    Yields:
        The repository.
    """
    if kind == "fake":
        yield job_fakes.InMemoryJobRepository()
        return
    client = dynamodb_store.build_client(
        config.DynamoDbSettings(
            endpoint_url="http://localhost:8000",
            access_key_id=pydantic.SecretStr("local"),
            secret_access_key=pydantic.SecretStr("local"),
        )
    )
    table = f"jobs-{uuid.uuid4().hex}"
    repository = dynamodb_jobs.DynamoDbJobRepository(client, table)
    await repository.ensure_table()
    try:
        yield repository
    finally:
        client.delete_table(TableName=table)


def job(job_id: str) -> jobs.Job:
    """Builds a queued extraction job with every optional field set.

    Args:
        job_id: Id of the job.

    Returns:
        The job.
    """
    return jobs.Job(
        job_id=job_id,
        kind=jobs.JobKind.EXTRACT,
        status=jobs.JobStatus.QUEUED,
        input_key=f"inputs/{job_id}.pdf",
        attempts=0,
        max_attempts=3,
        created_at=NOW,
        updated_at=NOW,
        document_key="memo.pdf",
        content_hash="h",
        order=4,
        names=(extraction.QueryName("María", "González"),),
    )


def at(minutes: float) -> datetime.datetime:
    """Returns ``NOW`` shifted by ``minutes``.

    Args:
        minutes: The shift.

    Returns:
        The time.
    """
    return NOW + datetime.timedelta(minutes=minutes)


@pytest.mark.parametrize("kind", KINDS)
async def test_lifecycle_counts_attempts_and_terminal_states_are_final(
    kind: str,
) -> None:
    async with repository_of(kind) as repository:
        created = job("j1")
        await repository.create(created)
        stored = await repository.get("j1")
        first = await repository.claim("j1", at(5))
        again = await repository.claim("j1", at(5))
        await repository.mark_retrying("j1", "ocr.engine_failure", "busy")
        second = await repository.claim("j1", at(10))
        done = await repository.mark_succeeded("j1", "results/j1.json")
        after_done = [
            await repository.claim("j1", at(15)),
            await repository.mark_retrying("j1", "x", "y"),
            await repository.mark_dead_lettered("j1", "x", "y"),
        ]

    assert stored == created
    assert first is not None and (first.status, first.attempts) == (
        jobs.JobStatus.RUNNING,
        1,
    )
    assert again is None
    assert second is not None and second.attempts == 2
    assert second.last_error_code == "ocr.engine_failure"
    assert done is not None and (done.status, done.result_key) == (
        jobs.JobStatus.SUCCEEDED,
        "results/j1.json",
    )
    assert after_done == [None, None, None]


@pytest.mark.parametrize("kind", KINDS)
async def test_racing_claims_have_exactly_one_winner(kind: str) -> None:
    async with repository_of(kind) as repository:
        await repository.create(job("j1"))

        claims = await asyncio.gather(
            *(repository.claim("j1", at(5)) for _ in range(5))
        )

    assert sum(claim is not None for claim in claims) == 1


@pytest.mark.parametrize("kind", KINDS)
async def test_listings_filter_by_state_and_lapsed_lease(kind: str) -> None:
    async with repository_of(kind) as repository:
        for job_id in ("lapsed", "alive", "waiting"):
            await repository.create(job(job_id))
        await repository.claim("lapsed", at(-1))
        await repository.claim("alive", at(30))

        expired = await repository.list_expired_leases(NOW)
        queued = await repository.list_by_status(jobs.JobStatus.QUEUED, 10)
        running = await repository.list_by_status(jobs.JobStatus.RUNNING, 10)

    assert [j.job_id for j in expired] == ["lapsed"]
    assert [j.job_id for j in queued] == ["waiting"]
    assert sorted(j.job_id for j in running) == ["alive", "lapsed"]
    assert queued[0] == job("waiting")
