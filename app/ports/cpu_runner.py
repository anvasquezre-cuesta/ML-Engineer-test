"""Port for running blocking, CPU-bound work from async use cases."""

import abc
from collections.abc import Callable


class CpuRunner(abc.ABC):
    """Runs synchronous CPU-bound callables without blocking the event loop.

    Implementations must propagate the caller's context variables (for
    example the logging ``request_id`` and ``job_id``) into the callable.
    """

    @abc.abstractmethod
    async def run[**P, R](
        self, fn: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs
    ) -> R:
        """Runs ``fn(*args, **kwargs)`` and returns its result.

        Args:
            fn: The synchronous callable to run.
            *args: Positional arguments for ``fn``.
            **kwargs: Keyword arguments for ``fn``.

        Returns:
            The value returned by ``fn``.
        """
