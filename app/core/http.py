"""Timeout/retry helpers for external calls.

 ponytail: generic callable retry with fixed backoff; ceiling is "no
 per-operation circuit breaker, no jitter". Add if external failures become
 correlated under load.
"""

import time

from app.core.errors import ExternalServiceError


def with_retries(
    fn,
    *,
    retries: int,
    backoff_seconds: float,
    operation: str,
) -> object:
    """Call fn() up to retries+1 times.

    On exception, sleep backoff_seconds and retry. After exhausting retries,
    raise ExternalServiceError with the last exception.
    """
    last = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(backoff_seconds)
    raise ExternalServiceError(
        f"{operation} failed after {retries} retries: {last}"
    ) from last
