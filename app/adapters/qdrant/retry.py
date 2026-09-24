"""Bounded retries for Qdrant calls, which the client does not retry itself."""

from collections.abc import Awaitable
from collections.abc import Callable

from app import config


async def call_with_retries[T](  # noqa: DOC501, DOC503
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
    """
    raise NotImplementedError
