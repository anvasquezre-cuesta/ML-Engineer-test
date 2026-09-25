"""LlmObservability that traces every chat-model call to Langfuse."""

from typing import Any

import langfuse
from langfuse import langchain as langfuse_langchain

from app import config
from app.ports import llm_observability


class LangfuseObservability(llm_observability.LlmObservability):
    """Reports each call through Langfuse's LangChain callback handler."""

    def __init__(
        self,
        settings: config.LlmObservabilitySettings,
        public_key: str,
        secret_key: str,
    ) -> None:
        """Creates the Langfuse client once, with explicit credentials.

        Args:
            settings: Langfuse host.
            public_key: Project public key.
            secret_key: Project secret key.
        """
        self._client = langfuse.Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=settings.langfuse_host,
        )
        self._handler = langfuse_langchain.CallbackHandler(
            public_key=public_key
        )

    def callbacks(self) -> list[Any]:
        """Returns the Langfuse callback handler.

        Returns:
            A one-element list.
        """
        return [self._handler]

    def flush(self) -> None:
        """Sends buffered traces to Langfuse."""
        self._client.flush()
