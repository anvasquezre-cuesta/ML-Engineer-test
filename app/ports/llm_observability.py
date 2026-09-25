"""Port for tracing language-model calls."""

import abc
from typing import Any


class LlmObservability(abc.ABC):
    """Supplies the tracing callbacks attached to every model call."""

    @abc.abstractmethod
    def callbacks(self) -> list[Any]:
        """Returns the callback handlers the chat model reports to.

        The handlers are LangChain callback handlers; the port stays free
        of LangChain, so they are typed loosely here.

        Returns:
            The handlers; empty when tracing is off.
        """

    @abc.abstractmethod
    def flush(self) -> None:
        """Sends buffered traces, e.g. before the process exits."""
