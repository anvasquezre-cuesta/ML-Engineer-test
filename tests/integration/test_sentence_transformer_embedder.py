import math
from collections.abc import Iterator

import pytest

from app.domain.errors import EmbeddingModelUnavailable
from app.infrastructure.sentence_transformer_embedder import SentenceTransformerEmbedder
from app.infrastructure.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def embedder(env_settings: Settings) -> Iterator[SentenceTransformerEmbedder]:
    try:
        yield SentenceTransformerEmbedder(env_settings.embedding_model)
    except EmbeddingModelUnavailable as exc:
        pytest.skip(f"Embedding model not available (offline?): {exc}")


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_passages_become_normalized_384_dimensional_vectors(
    embedder: SentenceTransformerEmbedder,
) -> None:
    vectors = embedder.embed_passages(["The board approved the budget.", "Q3 2024"])

    assert len(vectors) == 2
    for vector in vectors:
        assert len(vector) == 384
        assert math.sqrt(sum(v * v for v in vector)) == pytest.approx(1.0, abs=1e-4)


def test_question_is_closer_to_its_answer_than_to_an_unrelated_passage(
    embedder: SentenceTransformerEmbedder,
) -> None:
    answer, unrelated = embedder.embed_passages(
        [
            "Richard Hernandez, Chairman of the Board, called the meeting to order.",
            "The full migration to AWS is expected to be completed by Q3 2024.",
        ]
    )

    question = embedder.embed_question("Who chairs the board?")

    assert _cosine(question, answer) > _cosine(question, unrelated)


def test_no_passages_gives_no_vectors(embedder: SentenceTransformerEmbedder) -> None:
    assert embedder.embed_passages([]) == []


def test_tokens_are_counted_with_the_model_tokenizer(
    embedder: SentenceTransformerEmbedder,
) -> None:
    # Subword tokens, special tokens excluded (value probed with the e5 tokenizer).
    assert embedder.count_tokens("Dr. Kevin O’Brien noted potential regulatory implications.") == 15
    assert embedder.count_tokens("") == 0


def test_unknown_model_fails_with_a_specific_error() -> None:
    with pytest.raises(EmbeddingModelUnavailable, match="no-such-model"):
        SentenceTransformerEmbedder("nonexistent-org/no-such-model-xyz")
