"""Llm that reports a missing configuration on every call."""

from typing import NoReturn

from app.domain import errors
from app.domain import rag
from app.ports import llm


class UnconfiguredLlm(llm.Llm):
    """Fails each question, so the rest of the service still starts."""

    def __init__(self, detail: str) -> None:
        """Initializes the adapter.

        Args:
            detail: What is missing, e.g. the unset setting.
        """
        self._detail = detail

    async def complete(self, prompt: rag.LlmPrompt) -> NoReturn:
        """Refuses to generate.

        Args:
            prompt: Ignored.

        Raises:
            errors.LlmNotConfiguredError: Always.
        """
        raise errors.LlmNotConfiguredError(self._detail)
