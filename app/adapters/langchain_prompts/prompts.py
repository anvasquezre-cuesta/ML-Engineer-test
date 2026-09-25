"""Prompt files rendered with LangChain ``PromptTemplate``."""

from collections.abc import Sequence
import pathlib

from langchain_core import prompts as lc_prompts

from app.domain import rag
from app.ports import prompts


class LangChainPrompts(prompts.Prompts):
    """Loads the prompt files of a directory once and renders them."""

    def __init__(self, directory: pathlib.Path) -> None:
        """Reads every template the service uses.

        Args:
            directory: Folder holding ``refusal.txt``, ``answer_system.md``,
                ``answer_user.md`` and ``passage.md``.
        """
        self._refusal = _read(directory / "refusal.txt")
        self._system = lc_prompts.PromptTemplate.from_template(
            _read(directory / "answer_system.md")
        )
        self._user = lc_prompts.PromptTemplate.from_template(
            _read(directory / "answer_user.md")
        )
        self._passage = lc_prompts.PromptTemplate.from_template(
            _read(directory / "passage.md")
        )

    @property
    def refusal(self) -> str:
        """Returns the exact sentence the model must use to refuse.

        Returns:
            The refusal sentence.
        """
        return self._refusal

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
        shown = "\n".join(
            self._passage.format(
                number=passage.number,
                document=passage.document_key,
                page=passage.page,
                text=passage.text,
            )
            for passage in passages
        )
        return rag.LlmPrompt(
            system=self._system.format(refusal=self._refusal),
            user=self._user.format(
                passages=shown, question=question, refusal=self._refusal
            ),
        )


def _read(path: pathlib.Path) -> str:
    """Reads a prompt file without its trailing newline.

    Args:
        path: The file.

    Returns:
        The file's text.
    """
    return path.read_text(encoding="utf-8").strip()
