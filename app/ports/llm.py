"""Port for generating answers with a language model."""

import abc

from app.domain.rag import LlmPrompt


class Llm(abc.ABC):
    """Chat language model behind a provider-neutral interface."""

    @abc.abstractmethod
    async def complete(self, prompt: LlmPrompt) -> str:  # noqa: DOC502
        """Generates a completion for ``prompt``.

        Args:
            prompt: System instructions and user message.

        Returns:
            The model's answer text.

        Raises:
            LlmNotConfiguredError: If no provider or credentials are set.
            LlmUnavailableError: If the provider fails after retries.
            LlmTimeoutError: If the provider does not answer in time.
        """
