"""Rules that turn retrieved chunks and a model completion into an answer."""

from collections.abc import Sequence
import dataclasses

from app.domain import rag

REFUSAL = "I cannot answer this from the provided documents."


@dataclasses.dataclass(frozen=True, slots=True)
class Answer:
    """An answer and the retrieved chunks it rests on.

    Attributes:
        text: The answer shown to the user; the canonical refusal sentence
            when ``refused``.
        sources: References to retrieved chunks, never to anything else.
        refused: Whether the passages did not contain the answer.
        cited: Whether ``sources`` come from the model's citation markers;
            ``False`` when every retrieved chunk is listed as a fallback.
    """

    text: str
    sources: tuple[str, ...]
    refused: bool
    cited: bool


REFUSED = Answer(text=REFUSAL, sources=(), refused=True, cited=False)


def source_reference(chunk: rag.Chunk) -> str:  # noqa: DOC501, DOC503
    """Formats the reference of one chunk as returned in ``sources``.

    The page fragment is 1-based, as ``#page=`` is defined for PDFs, while
    chunks store 0-based page numbers.

    Args:
        chunk: A retrieved chunk.

    Returns:
        ``<document_key>#page=<page_number + 1>&chunk=<chunk_index>``.
    """
    raise NotImplementedError


def build_prompt(  # noqa: DOC501, DOC503
    question: str, chunks: Sequence[rag.Chunk]
) -> rag.LlmPrompt:
    """Builds the grounded prompt for ``question``.

    Passages are numbered from 1 in rank order and delimited with their
    document and 1-based page. Bracketed numbers inside chunk text become
    parenthesised, so text in a document cannot pose as a citation marker.

    Args:
        question: The user's question.
        chunks: The retrieved chunks, best first.

    Returns:
        The system rules and the user message.
    """
    raise NotImplementedError


def read_answer(  # noqa: DOC501, DOC503
    completion: str, chunks: Sequence[rag.Chunk]
) -> Answer:
    """Interprets a model completion against the chunks it was shown.

    A completion containing the refusal sentence anywhere (case and
    punctuation ignored) is a refusal and cites nothing. Otherwise the
    ``[n]`` and ``[n, m]`` markers that point at a shown passage become the
    sources, deduplicated in the order first cited. A completion with no
    such marker lists every shown chunk instead.

    Args:
        completion: The model's text.
        chunks: The chunks in the order they were numbered in the prompt.

    Returns:
        The answer and its sources.
    """
    raise NotImplementedError
