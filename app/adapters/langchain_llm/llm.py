"""Llm backed by a LangChain chat model, with a deadline and error mapping."""

from langchain_core.language_models import chat_models

from app.domain import rag
from app.ports import llm
from app.ports import llm_observability


class LangChainLlm(llm.Llm):
    """Sends the prompt as system and user messages and returns the text."""

    def __init__(
        self,
        chat: chat_models.BaseChatModel,
        observability: llm_observability.LlmObservability,
        deadline_s: float,
    ) -> None:
        """Initializes the adapter.

        Args:
            chat: The chat model, loaded once.
            observability: Supplies the tracing callbacks.
            deadline_s: Total time one call may take, SDK retries included.
        """
        self._chat = chat
        self._observability = observability
        self._deadline_s = deadline_s

    async def complete(  # noqa: DOC501, DOC503
        self, prompt: rag.LlmPrompt
    ) -> str:
        """Generates a completion for ``prompt``.

        Timeouts, including the overall deadline, become
        ``LlmTimeoutError``; connection failures, throttling and server
        errors that outlast the SDK's retries become ``LlmUnavailableError``;
        rejected credentials become ``LlmNotConfiguredError``. Anything else
        is raised unchanged.

        Args:
            prompt: System instructions and user message.

        Returns:
            The text of the completion, without reasoning blocks.
        """
        raise NotImplementedError
