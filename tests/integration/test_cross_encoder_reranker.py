from collections.abc import Iterator

import pytest

from app.domain.errors import RerankerUnavailable
from app.infrastructure.cross_encoder_reranker import CrossEncoderReranker
from app.infrastructure.settings import Settings

pytestmark = pytest.mark.integration

CHAIRMAN = "Richard Hernandez, Chairman of the Board, called the meeting to order."
MIGRATION = "The full migration to AWS is expected to be completed by Q3 2024."


@pytest.fixture(scope="module")
def reranker(env_settings: Settings) -> Iterator[CrossEncoderReranker]:
    try:
        yield CrossEncoderReranker(env_settings.reranker_model)
    except RerankerUnavailable as exc:
        pytest.skip(f"Reranker model not available (offline?): {exc}")


def test_the_passage_that_answers_scores_higher(reranker: CrossEncoderReranker) -> None:
    chairman, migration = reranker.score("Who chairs the board?", [CHAIRMAN, MIGRATION])

    assert chairman > migration


def test_one_score_per_passage_in_input_order(reranker: CrossEncoderReranker) -> None:
    passages = [
        CHAIRMAN,
        MIGRATION,
        "Elizabeth Park presented the Q4 financial results.",
        "Jennifer Liu confirmed quorum was present.",
        "The next meeting is scheduled for March 18, 2024.",
    ]

    scores = reranker.score("Who chairs the board?", passages)
    reversed_scores = reranker.score("Who chairs the board?", passages[::-1])

    assert len(scores) == 5
    assert reversed_scores == pytest.approx(scores[::-1], abs=1e-4)


def test_a_spanish_question_ranks_english_passages(reranker: CrossEncoderReranker) -> None:
    chairman, migration = reranker.score("¿Quién preside la junta?", [CHAIRMAN, MIGRATION])

    assert chairman > migration


def test_no_passages_never_calls_the_model(
    reranker: CrossEncoderReranker, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []
    model = reranker._model  # the loaded CrossEncoder; spy on its predict
    monkeypatch.setattr(model, "predict", lambda *args, **kwargs: calls.append(args))

    assert reranker.score("Who chairs the board?", []) == []
    assert calls == []


def test_unknown_model_fails_with_a_specific_error() -> None:
    with pytest.raises(RerankerUnavailable, match="no-such-model"):
        CrossEncoderReranker("nonexistent-org/no-such-model-xyz")
