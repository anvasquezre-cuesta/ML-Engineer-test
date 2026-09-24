"""Bounded retries for Qdrant calls, which the client does not retry itself."""

from collections.abc import Awaitable
from collections.abc import Callable

import httpx
from qdrant_client.common import client_exceptions
from qdrant_client.http import exceptions
import structlog
import tenacity

from app import config
from app.domain import errors

TRANSIENT_STATUS = frozenset({502, 503, 504})

log = structlog.stdlib.get_logger(__name__)


def is_transient(exc: BaseException) -> bool:
    """Tells whether retrying the same Qdrant call may succeed.

    Args:
        exc: The error the call raised.

    Returns:
        ``True`` for rate limiting, 502/503/504 and transport failures.
    """
    if isinstance(exc, client_exceptions.ResourceExhaustedResponse):
        return True
    if isinstance(exc, exceptions.UnexpectedResponse):
        return exc.status_code in TRANSIENT_STATUS
    if isinstance(exc, exceptions.ResponseHandlingException):
        # The same wrapper carries response-parsing errors, never worth a retry.
        return isinstance(exc.source, httpx.TransportError)
    return False


def _is_timeout(exc: BaseException) -> bool:
    """Tells whether ``exc`` is a Qdrant timeout.

    Args:
        exc: A transient error.

    Returns:
        ``True`` if the transport timed out.
    """
    return isinstance(exc, exceptions.ResponseHandlingException) and isinstance(
        exc.source, httpx.TimeoutException
    )


class _RetryAfterWait(tenacity.wait.wait_base):
    """Exponential backoff with jitter that waits at least Retry-After."""

    def __init__(self, settings: config.QdrantSettings) -> None:
        """Initializes the wait.

        Args:
            settings: Backoff bounds.
        """
        self._backoff = tenacity.wait_exponential_jitter(
            initial=settings.backoff_initial_s, max=settings.backoff_max_s
        )

    def __call__(self, retry_state: tenacity.RetryCallState) -> float:
        """Returns the seconds to wait before the next attempt.

        Args:
            retry_state: State of the current retry loop.

        Returns:
            The backoff, raised to Qdrant's Retry-After after a 429.
        """
        backoff = self._backoff(retry_state)
        outcome = retry_state.outcome
        error = outcome.exception() if outcome is not None else None
        if isinstance(error, client_exceptions.ResourceExhaustedResponse):
            return max(float(error.retry_after_s), backoff)
        return backoff


async def call_with_retries[T](
    operation: Callable[[], Awaitable[T]],
    settings: config.QdrantSettings,
    *,
    action: str,
) -> T:
    """Runs ``operation``, retrying transient Qdrant failures.

    Transient failures are rate limiting (429), 502/503/504 responses and
    transport errors or timeouts. Anything else, including cancellation and
    response-parsing errors, propagates at once. Retries stop after
    ``max_retries`` or at ``deadline_s``, whichever comes first.

    Args:
        operation: One Qdrant call; invoked again for each attempt.
        settings: Retry budget and backoff.
        action: Name of the operation for logs, e.g. ``upsert``.

    Returns:
        The operation's result.

    Raises:
        errors.VectorStoreTimeoutError: If the last attempt timed out.
        errors.VectorStoreUnavailableError: If transient failures outlast
            the budget.
    """

    def log_retry(state: tenacity.RetryCallState) -> None:
        outcome = state.outcome
        error = outcome.exception() if outcome is not None else None
        log.warning(
            "vector_store.retry",
            action=action,
            attempt=state.attempt_number,
            error_type=type(error).__name__,
        )

    retrying = tenacity.AsyncRetrying(
        retry=tenacity.retry_if_exception(is_transient),
        stop=tenacity.stop_after_attempt(settings.max_retries + 1)
        | tenacity.stop_after_delay(settings.deadline_s),
        wait=_RetryAfterWait(settings),
        before_sleep=log_retry,
    )
    try:
        return await retrying(operation)
    except tenacity.RetryError as exhausted:
        last = exhausted.last_attempt.exception()
        if last is not None and _is_timeout(last):
            raise errors.VectorStoreTimeoutError() from last
        raise errors.VectorStoreUnavailableError() from last
