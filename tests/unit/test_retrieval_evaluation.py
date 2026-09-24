"""Relevance by evidence quote, and metrics from a hand-computed ranking."""

import pytest

from app.domain import rag
from evaluation import dataset
from evaluation import retrieval

pytestmark = pytest.mark.xfail(
    strict=True, raises=NotImplementedError, reason="evaluation not built"
)


def chunk(document: str, page: int, index: int, text: str) -> rag.Chunk:
    """Builds a chunk of ``document``.

    Args:
        document: Document key.
        page: 0-based page number.
        index: Chunk position on the page.
        text: Chunk text.

    Returns:
        The chunk.
    """
    return rag.Chunk(document, "h", page, index, 0, len(text), text, "t")


def test_relevance_needs_the_quote_on_the_evidence_page() -> None:
    question = dataset.Question(
        id="ceo",
        question="What is Margaret Thompson's role?",
        answer="CEO",
        evidence=[
            dataset.Evidence(
                document="memo.pdf",
                page=0,
                quote="From: Margaret Thompson, CEO",
            ),
            dataset.Evidence(
                document="report.pdf",
                page=1,
                quote="Reviewed by: Margaret Thompson, CEO",
            ),
        ],
    )
    chunks = [
        chunk("memo.pdf", 0, 0, "MEMO\nFrom:  Margaret\nThompson, CEO\nDate"),
        chunk("memo.pdf", 1, 0, "From: Margaret Thompson, CEO"),
        chunk("report.pdf", 1, 3, "Reviewed by: Margaret Thompson, CEO."),
        chunk("report.pdf", 1, 4, "Reviewed by Margaret Thompson"),
    ]

    assert retrieval.relevant_chunks(question, chunks) == {
        "memo.pdf#0#0",
        "report.pdf#1#3",
    }


def test_metrics_follow_rank_order_and_the_recall_cut_off() -> None:
    rankings = {"q1": ["a", "x", "b"], "q2": ["y", "c"]}
    relevant = {"q1": {"a", "b"}, "q2": {"c"}}

    metrics = retrieval.score(rankings, relevant, k=1)

    assert metrics.mrr_at_10 == pytest.approx((1 + 1 / 2) / 2)
    assert metrics.recall_at_k == pytest.approx((1 / 2 + 0) / 2)
    assert metrics.k == 1
