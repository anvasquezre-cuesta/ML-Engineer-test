"""CpuRunner backed by worker threads with a concurrency cap."""

import asyncio
from collections.abc import Callable
import functools

from app.ports.cpu_runner import CpuRunner


class ThreadCpuRunner(CpuRunner):
    """Runs callables in worker threads, at most ``max_concurrency`` at once.

    ``asyncio.to_thread`` copies the caller's context, so log context bound
    by the request or job is visible inside the callable.

    Attributes:
        max_concurrency: Maximum number of callables running at the same time.
    """

    def __init__(self, max_concurrency: int) -> None:
        """Initializes the runner.

        Args:
            max_concurrency: Maximum number of callables running at once.

        Raises:
            ValueError: If ``max_concurrency`` is not positive.
        """
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1.")
        self.max_concurrency = max_concurrency
        self._slots = asyncio.Semaphore(max_concurrency)

    async def run[**P, R](
        self, fn: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs
    ) -> R:
        """Runs ``fn(*args, **kwargs)`` in a worker thread.

        Args:
            fn: The synchronous callable to run.
            *args: Positional arguments for ``fn``.
            **kwargs: Keyword arguments for ``fn``.

        Returns:
            The value returned by ``fn``.
        """
        async with self._slots:
            return await asyncio.to_thread(
                functools.partial(fn, *args, **kwargs)
            )
