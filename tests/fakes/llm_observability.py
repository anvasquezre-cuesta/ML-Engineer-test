"""Fake LlmObservability whose handler records every chat-model call."""

from typing import Any

from langchain_core import callbacks

from app.ports import llm_observability


class RecordingHandler(callbacks.BaseCallbackHandler):
    """Records the messages of every chat-model call it sees.

    Attributes:
        calls: The message batches, one entry per call.
    """

    def __init__(self) -> None:
        """Initializes an empty record."""
        self.calls: list[list[list[Any]]] = []

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        """Records the messages sent to the model.

        Args:
            serialized: The model's serialized form.
            messages: The message batches.
            **kwargs: Run metadata.
        """
        self.calls.append(messages)


class RecordingObservability(llm_observability.LlmObservability):
    """Hands out one recording handler.

    Attributes:
        handler: The handler every call reports to.
    """

    def __init__(self) -> None:
        """Creates the handler."""
        self.handler = RecordingHandler()

    def callbacks(self) -> list[Any]:
        """Returns the recording handler.

        Returns:
            A one-element list.
        """
        return [self.handler]

    def flush(self) -> None:
        """Does nothing; records are kept in memory."""
