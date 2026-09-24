"""Scoring rules for generated answers that need no model to apply."""

from collections.abc import Sequence
from collections.abc import Set

from app.domain import answering
from app.domain import rag


def strip_markers(text: str) -> str:  # noqa: DOC501, DOC503
    """Removes ``[n]`` and ``[n, m]`` citation markers from an answer.

    Judges of answer relevancy count markers as irrelevant text, so answers
    are judged without them.

    Args:
        text: The answer as returned by ``/ask``.

    Returns:
        The answer text without markers or the spaces left before them.
    """
    raise NotImplementedError


def cites_evidence(  # noqa: DOC501, DOC503
    answer: answering.Answer,
    shown: Sequence[rag.Chunk],
    relevant: Set[str],
) -> bool:
    """Tells whether an answer cites a chunk that states the answer.

    Only cited sources count. The fallback that lists every shown chunk
    cites nothing, so it never counts as citing the evidence.

    Args:
        answer: The answer read from the completion.
        shown: The chunks in the order they were numbered in the prompt.
        relevant: Ids (``document#page#index``) of the evidence chunks.

    Returns:
        Whether a cited source is an evidence chunk.
    """
    raise NotImplementedError
