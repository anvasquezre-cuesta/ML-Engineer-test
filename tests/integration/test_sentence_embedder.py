"""The real sentence-transformers adapter. Skipped if the model cannot be loaded (offline)."""

import math

import pytest
from structlog.testing import capture_logs

from app.adapters.sentence_embedder import SentenceTransformerEmbedder
from app.core.config import RAGSettings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def embedder() -> SentenceTransformerEmbedder:
    try:
        return SentenceTransformerEmbedder(RAGSettings())
    except OSError as exc:  # model not cached and no network
        pytest.skip(f"embedding model unavailable: {exc}")


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_vectors_are_normalised_and_384_dimensional(embedder: SentenceTransformerEmbedder) -> None:
    (vector,) = embedder.embed(["Robert Chen was promoted to Vice President of Engineering."])

    assert len(vector) == 384
    assert math.sqrt(sum(v * v for v in vector)) == pytest.approx(1.0, abs=1e-5)


def test_related_texts_are_closer_than_unrelated(embedder: SentenceTransformerEmbedder) -> None:
    question, related, unrelated = embedder.embed(
        [
            "Who was promoted to Vice President of Engineering?",
            "Robert Chen has been promoted to Vice President of Engineering.",
            "Total research budget: $4.2M. External grants secured: $1.8M.",
        ]
    )

    assert _cosine(question, related) > _cosine(question, unrelated) + 0.2


def test_empty_input_needs_no_model_call(embedder: SentenceTransformerEmbedder) -> None:
    assert embedder.embed([]) == []


def test_truncation_is_logged(embedder: SentenceTransformerEmbedder) -> None:
    with capture_logs() as logs:
        embedder.embed(["word " * 400])

    (warning,) = [e for e in logs if e["event"] == "embedding_input_truncated"]
    assert warning["truncated_chunks"] == 1
    assert warning["max_tokens"] == 256
