"""Retrieval gate: hybrid search on the frozen sample text stays good."""

import pytest

from app import config
from evaluation import retrieval

pytestmark = [
    pytest.mark.integration,
    pytest.mark.xfail(
        strict=True, raises=NotImplementedError, reason="evaluation not built"
    ),
]


async def test_hybrid_retrieval_keeps_its_measured_quality() -> None:
    settings = config.Settings()

    metrics = await retrieval.evaluate_samples(settings)

    assert metrics.k == settings.qdrant.top_k
    assert metrics.ndcg_at_10 >= 0.90
    assert metrics.mrr_at_10 >= 0.89
    assert metrics.recall_at_k >= 0.94
