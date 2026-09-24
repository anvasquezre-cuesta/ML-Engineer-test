"""Answer scoring: markers never reach the judge; fallbacks cite nothing."""

import pytest

from app.domain import answering
from app.domain import rag
from evaluation import answers

pytestmark = pytest.mark.xfail(
    strict=True, raises=NotImplementedError, reason="answer scoring not built"
)

SHOWN = [
    rag.Chunk("memo.pdf", "h", 0, 0, 0, 10, "Robert Chen", "t"),
    rag.Chunk("minutes.pdf", "h", 1, 2, 0, 10, "Yuki Tanaka", "t"),
]
EVIDENCE = {"minutes.pdf#1#2"}


def test_markers_are_removed_but_bracketless_numbers_stay() -> None:
    text = "Revenue grew 12% [1] in Q4 (see 2024) [2, 3][1]."

    assert answers.strip_markers(text) == "Revenue grew 12% in Q4 (see 2024)."


def test_only_a_cited_evidence_chunk_counts() -> None:
    cited = answering.Answer(
        text="Tanaka [2].",
        sources=(answering.source_reference(SHOWN[1]),),
        refused=False,
        cited=True,
    )
    fallback = answering.Answer(
        text="Tanaka.",
        sources=tuple(answering.source_reference(c) for c in SHOWN),
        refused=False,
        cited=False,
    )
    wrong = answering.Answer(
        text="Chen [1].",
        sources=(answering.source_reference(SHOWN[0]),),
        refused=False,
        cited=True,
    )

    assert answers.cites_evidence(cited, SHOWN, EVIDENCE)
    assert not answers.cites_evidence(fallback, SHOWN, EVIDENCE)
    assert not answers.cites_evidence(wrong, SHOWN, EVIDENCE)
