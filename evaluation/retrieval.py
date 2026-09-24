"""Retrieval quality on the samples: relevance, metrics and the gate run."""

from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses

from app import config
from app.domain import rag
from evaluation import dataset


@dataclasses.dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    """Mean retrieval quality over the judged questions.

    Attributes:
        ndcg_at_10: Normalized discounted cumulative gain of the top 10.
        mrr_at_10: Mean reciprocal rank of the first relevant chunk in the
            top 10.
        recall_at_k: Share of relevant chunks within the top ``k``.
        k: The cut-off of ``recall_at_k``, the configured ``top_k``.
    """

    ndcg_at_10: float
    mrr_at_10: float
    recall_at_k: float
    k: int


def relevant_chunks(  # noqa: DOC501, DOC503
    question: dataset.Question, chunks: Sequence[rag.Chunk]
) -> set[str]:
    """Finds the chunks that state a question's answer.

    A chunk is relevant when it is on the evidence's document and page and
    contains the evidence quote, whitespace ignored, so the result does not
    depend on where the chunker cuts.

    Args:
        question: The question and its evidence.
        chunks: Every chunk of the sample documents.

    Returns:
        The ids (``document#page#index``) of the relevant chunks.
    """
    raise NotImplementedError


def score(  # noqa: DOC501, DOC503
    rankings: Mapping[str, Sequence[str]],
    relevant: Mapping[str, set[str]],
    k: int,
) -> RetrievalMetrics:
    """Scores ranked chunk ids against the relevant ones with pytrec_eval.

    Args:
        rankings: Chunk ids per question id, best first.
        relevant: Relevant chunk ids per question id.
        k: Recall cut-off.

    Returns:
        The mean metrics over the questions in ``relevant``.
    """
    raise NotImplementedError


async def evaluate_samples(  # noqa: DOC501, DOC503
    settings: config.Settings,
) -> RetrievalMetrics:
    """Measures hybrid retrieval on the frozen sample OCR text.

    The pages are chunked, embedded and searched with the service's own
    chunker, FastEmbed models and Qdrant adapter (in memory), at the
    configured ``top_k``.

    Args:
        settings: The service configuration.

    Returns:
        The metrics over the answerable sample questions.
    """
    raise NotImplementedError
