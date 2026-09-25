"""Grounding rules: sources come only from shown chunks; refusals cite none."""

import hypothesis
from hypothesis import strategies as st

from app.domain import answering
from app.domain import rag


def chunk(document_key: str, page_number: int, chunk_index: int) -> rag.Chunk:
    """Builds a retrieved chunk whose text names its position.

    Args:
        document_key: Identity of the document.
        page_number: 0-based page index.
        chunk_index: Position of the chunk within its page.

    Returns:
        The chunk.
    """
    text = f"{document_key} page {page_number} chunk {chunk_index}"
    return rag.Chunk(
        document_key, "hash", page_number, chunk_index, 0, len(text), text, "t"
    )


SHOWN = [
    chunk("memo.pdf", 0, 0),
    chunk("minutes.pdf", 1, 2),
    chunk("report.pdf", 0, 1),
]
REFUSAL = "I cannot answer this from the provided documents."
EVERY_SOURCE = (
    "memo.pdf#page=1&chunk=0",
    "minutes.pdf#page=2&chunk=2",
    "report.pdf#page=1&chunk=1",
)


def test_cited_passages_become_sources_in_first_cited_order() -> None:
    completion = "Tanaka leads it [2]; see also [7] and [2, 1] or [0]."

    answer = answering.read_answer(completion, SHOWN, REFUSAL)

    assert answer == answering.Answer(
        text=completion,
        sources=("minutes.pdf#page=2&chunk=2", "memo.pdf#page=1&chunk=0"),
        refused=False,
        cited=True,
    )


@hypothesis.given(st.text(alphabet="[]0123456789, ab", max_size=40))
def test_sources_never_name_a_chunk_that_was_not_shown(
    completion: str,
) -> None:
    answer = answering.read_answer(completion, SHOWN, REFUSAL)

    assert set(answer.sources) <= set(EVERY_SOURCE)


def test_refusal_after_a_preamble_cites_nothing() -> None:
    completion = (
        "Dr. Fatima Al-Rashidi leads a division [1]. However, i CANNOT "
        "answer this from the provided documents"
    )

    answer = answering.read_answer(completion, SHOWN, REFUSAL)

    assert answer == answering.refused(REFUSAL)


def test_answer_without_markers_lists_every_shown_chunk() -> None:
    answer = answering.read_answer("Robert Chen.", SHOWN, REFUSAL)

    assert (answer.sources, answer.refused, answer.cited) == (
        EVERY_SOURCE,
        False,
        False,
    )
