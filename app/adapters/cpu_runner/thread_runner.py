"""CpuRunner backed by worker threads with a concurrency cap."""

from collections.abc import Callable

from app.ports.cpu_runner import CpuRunner


class ThreadCpuRunner(CpuRunner):
    """Runs callables in worker threads, at most ``max_concurrency`` at once.

    Attributes:
        max_concurrency: Maximum number of callables running at the same time.
    """

    def __init__(self, max_concurrency: int) -> None:
        """Initializes the runner.

        Args:
            max_concurrency: Maximum number of callables running at once.
        """
        self.max_concurrency = max_concurrency

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

        Raises:
            NotImplementedError: Always; the thread runner is not built yet.
        """
        raise NotImplementedError
