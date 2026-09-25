"""Port for the prompt text sent to the language model."""

import abc
from collections.abc import Sequence

from app.domain import rag


class Prompts(abc.ABC):
    """Prompt templates loaded once and rendered for each question."""

    @property
    @abc.abstractmethod
    def refusal(self) -> str:
        """Returns the exact sentence the model must use to refuse.

        Returns:
            The refusal sentence.
        """

    @abc.abstractmethod
    def answer(
        self, question: str, passages: Sequence[rag.Passage]
    ) -> rag.LlmPrompt:
        """Renders the grounded answer prompt.

        Args:
            question: The user's question.
            passages: The numbered passages, in the order they are shown.

        Returns:
            The system rules and the user message.
        """
