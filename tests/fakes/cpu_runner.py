"""Fake CpuRunner that runs callables inline on the calling thread."""

from collections.abc import Callable

from app.ports import cpu_runner


class InlineCpuRunner(cpu_runner.CpuRunner):
    """Runs callables synchronously in the caller's thread and context."""

    async def run[**P, R](
        self, fn: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs
    ) -> R:
        """Runs ``fn(*args, **kwargs)`` inline.

        Args:
            fn: The synchronous callable to run.
            *args: Positional arguments for ``fn``.
            **kwargs: Keyword arguments for ``fn``.

        Returns:
            The value returned by ``fn``.
        """
        return fn(*args, **kwargs)
