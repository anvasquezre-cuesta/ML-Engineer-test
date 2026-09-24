"""Scoring rules for generated answers that need no model to apply."""

from collections.abc import Sequence
from collections.abc import Set
import re

from app.domain import answering
from app.domain import rag
from evaluation import retrieval

_MARKERS = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")


def strip_markers(text: str) -> str:
    """Removes ``[n]`` and ``[n, m]`` citation markers from an answer.

    Judges of answer relevancy count markers as irrelevant text, so answers
    are judged without them.

    Args:
        text: The answer as returned by ``/ask``.

    Returns:
        The answer text without markers or the spaces left before them.
    """
    return _MARKERS.sub("", text)


def cites_evidence(
    answer: answering.Answer,
    shown: Sequence[rag.Chunk],
    relevant: Set[str],
) -> bool:
    """Tells whether an answer cites a chunk that states the answer.

    Only cited sources count. The fallback that lists every shown chunk
    cites nothing, so it never counts as citing the evidence.

    Args:
        answer: The answer read from the completion.
        shown: The chunks the answer could cite.
        relevant: Ids (``document#page#index``) of the evidence chunks.

    Returns:
        Whether a cited source is an evidence chunk.
    """
    if not answer.cited:
        return False
    cited = set(answer.sources)
    return any(
        retrieval.chunk_id(chunk) in relevant
        for chunk in shown
        if answering.source_reference(chunk) in cited
    )


def hedged(completion: str, shown: Sequence[rag.Chunk], refusal: str) -> bool:
    """Tells whether a completion cites passages and also refuses.

    The parser reads such a completion as a refusal, which hides that the
    model answered part of the question.

    Args:
        completion: The model's raw text.
        shown: The chunks the completion could cite.
        refusal: The refusal sentence.

    Returns:
        Whether the completion is a refusal with a valid citation.

    Raises:
        NotImplementedError: Always; not built yet.
    """
    raise NotImplementedError
