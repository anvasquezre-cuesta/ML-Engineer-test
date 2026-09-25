"""LlmObservability that traces nothing."""

from typing import Any

from app.ports import llm_observability


class NoopObservability(llm_observability.LlmObservability):
    """Used when no tracing backend is configured."""

    def callbacks(self) -> list[Any]:
        """Returns no handlers.

        Returns:
            An empty list.
        """
        return []

    def flush(self) -> None:
        """Does nothing; there is nothing buffered."""
