"""Fake Llm that returns a scripted completion and records its prompts."""

from app.domain import rag
from app.ports import llm


class ScriptedLlm(llm.Llm):
    """Answers every prompt with the same completion.

    Attributes:
        prompts: Every prompt received, in order.
    """

    def __init__(self, completion: str) -> None:
        """Initializes the fake.

        Args:
            completion: The text returned for every prompt.
        """
        self._completion = completion
        self.prompts: list[rag.LlmPrompt] = []

    async def complete(self, prompt: rag.LlmPrompt) -> str:
        """Records ``prompt`` and returns the scripted completion.

        Args:
            prompt: System instructions and user message.

        Returns:
            The scripted completion.
        """
        self.prompts.append(prompt)
        return self._completion
