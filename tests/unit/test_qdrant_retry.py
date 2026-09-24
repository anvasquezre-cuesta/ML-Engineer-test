"""Qdrant retries: bounded, transient failures only, mapped to domain errors."""

import asyncio
from collections.abc import Awaitable
from collections.abc import Callable

import httpx
import pytest
from qdrant_client.common import client_exceptions
from qdrant_client.http import exceptions

from app import config
from app.adapters.qdrant import retry
from app.domain import errors

SETTINGS = config.QdrantSettings(
    max_retries=2, backoff_initial_s=0, backoff_max_s=0, deadline_s=5
)


def http_error(status: int) -> exceptions.UnexpectedResponse:
    """Builds the error the client raises for an HTTP error status.

    Args:
        status: HTTP status code.

    Returns:
        The client exception.
    """
    return exceptions.UnexpectedResponse(
        status_code=status,
        reason_phrase="",
        content=b"",
        headers=httpx.Headers(),
    )


def failing(
    failures: list[BaseException], result: str = "ok"
) -> tuple[Callable[[], Awaitable[str]], list[int]]:
    """Returns an operation that raises ``failures`` in order, then succeeds.

    Args:
        failures: Exceptions to raise on the first calls.
        result: Value returned once the failures are used up.

    Returns:
        The operation and a list whose length counts the calls.
    """
    calls: list[int] = []

    async def operation() -> str:
        calls.append(1)
        if len(calls) <= len(failures):
            raise failures[len(calls) - 1]
        return result

    return operation, calls


async def test_transient_failures_are_retried_until_success() -> None:
    operation, calls = failing([http_error(503), http_error(503)])

    result = await retry.call_with_retries(operation, SETTINGS, action="upsert")

    assert (result, len(calls)) == ("ok", 3)


@pytest.mark.parametrize(
    ("failure", "domain_error"),
    [
        (http_error(503), errors.VectorStoreUnavailableError),
        (
            client_exceptions.ResourceExhaustedResponse("slow down", 0),
            errors.VectorStoreUnavailableError,
        ),
        (
            exceptions.ResponseHandlingException(httpx.ConnectError("refused")),
            errors.VectorStoreUnavailableError,
        ),
        (
            exceptions.ResponseHandlingException(httpx.ConnectTimeout("slow")),
            errors.VectorStoreTimeoutError,
        ),
    ],
    ids=["503", "429", "connection-refused", "timeout"],
)
async def test_persistent_transient_failure_stops_at_the_budget(
    failure: Exception, domain_error: type[errors.AppError]
) -> None:
    operation, calls = failing([failure] * 10)

    with pytest.raises(domain_error):
        await retry.call_with_retries(operation, SETTINGS, action="upsert")

    assert len(calls) == SETTINGS.max_retries + 1


@pytest.mark.parametrize(
    "failure",
    [
        http_error(400),
        exceptions.ResponseHandlingException(ValueError("bad payload")),
        asyncio.CancelledError(),
    ],
    ids=["400", "unparseable-response", "cancelled"],
)
async def test_other_failures_are_raised_at_once(
    failure: BaseException,
) -> None:
    operation, calls = failing([failure])

    with pytest.raises(type(failure)):
        await retry.call_with_retries(operation, SETTINGS, action="query")

    assert len(calls) == 1
