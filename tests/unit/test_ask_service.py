from collections.abc import Sequence

import pytest
from structlog.testing import capture_logs

from app.domain.errors import InvalidRequest, UpstreamUnavailable
from app.domain.models import Chunk, RetrievedChunk
from app.services.ask import NOT_FOUND_ANSWER, AskService, build_prompt, source_label
from tests.fakes import FakeEmbedder, FakeLLM


class FixedStore:
    """Returns the same scored chunks for every query, so thresholds are exact."""

    def __init__(self, *scored: tuple[str, int, float]) -> None:
        self.results = [
            RetrievedChunk(Chunk("doc", filename, page, 0, f"text of {filename} p{page}"), score)
            for filename, page, score in scored
        ]

    def query(self, vector: Sequence[float], top_k: int) -> list[RetrievedChunk]:
        return self.results[:top_k]

    def replace_document(self, *args: object) -> int:
        raise NotImplementedError

    def count(self) -> int:
        return len(self.results)


def _service(store: FixedStore, llm: FakeLLM, top_k: int = 5) -> AskService:
    return AskService(
        FakeEmbedder(), store, llm, top_k=top_k, min_similarity=0.33, context_min_similarity=0.30
    )


def test_no_llm_call_below_similarity_threshold() -> None:
    llm = FakeLLM()
    store = FixedStore(("minutes.pdf", 0, 0.291), ("report.pdf", 1, 0.288))

    result = _service(store, llm).ask("What is the 2025 marketing budget?")

    assert result.answer == NOT_FOUND_ANSWER
    assert result.sources == []
    assert llm.calls == []
    assert result.llm_called is False


def test_empty_store_is_not_found_without_llm_call() -> None:
    llm = FakeLLM()

    result = _service(FixedStore(), llm).ask("Anything?")

    assert (result.answer, result.sources, llm.calls) == (NOT_FOUND_ANSWER, [], [])


def test_sources_come_only_from_retrieved_chunks() -> None:
    # The model "cites" a document that was never retrieved; sources must not change.
    llm = FakeLLM("Robert Chen, according to secret_board_notes.pdf page 9.")
    store = FixedStore(("company_memo.pdf", 0, 0.382), ("minutes.pdf", 1, 0.192))

    result = _service(store, llm).ask("Who was promoted to Vice President of Engineering?")

    assert result.answer == llm.answer
    assert result.sources == ["company_memo.pdf#page=1"]


def test_gate_uses_the_best_match_and_context_keeps_a_weaker_answer_page() -> None:
    # Calibration case: the answer is on page 2 (0.325), behind page 1 (0.574).
    llm = FakeLLM("March 18, 2024.")
    store = FixedStore(
        ("meeting_minutes.pdf", 0, 0.574),
        ("meeting_minutes.pdf", 1, 0.325),
        ("company_memo.pdf", 0, 0.295),
    )

    result = _service(store, llm).ask("When is the next board meeting scheduled?")

    assert result.sources == ["meeting_minutes.pdf#page=1", "meeting_minutes.pdf#page=2"]
    (_, prompt) = llm.calls[0]
    assert "meeting_minutes.pdf p1" in prompt  # the page-2 text reached the model
    assert "company_memo.pdf p0" not in prompt  # 0.295 is below the context floor


@pytest.mark.parametrize(
    "reply", [NOT_FOUND_ANSWER, f'"{NOT_FOUND_ANSWER}"', NOT_FOUND_ANSWER.upper(), "", "   "]
)
def test_model_declining_to_answer_clears_the_sources(reply: str) -> None:
    # Seen with llama3.2:1b: the right page was retrieved, the model still said not found.
    llm = FakeLLM(reply)

    result = _service(FixedStore(("research_report.pdf", 1, 0.406)), llm).ask("Total budget?")

    assert result.sources == []
    assert result.llm_called is True


def test_an_answer_that_merely_mentions_finding_keeps_its_sources() -> None:
    llm = FakeLLM("The research budget could be found on page 2: $4.2M.")

    result = _service(FixedStore(("research_report.pdf", 1, 0.406)), llm).ask("Total budget?")

    assert result.sources == ["research_report.pdf#page=2"]


def test_prompt_numbers_the_passages_and_ends_with_the_question() -> None:
    context = FixedStore(("a.pdf", 0, 0.9), ("b.pdf", 2, 0.8)).results

    prompt = build_prompt("Who?", context)

    assert "[1] (a.pdf#page=1)\ntext of a.pdf p0" in prompt
    assert "[2] (b.pdf#page=3)\ntext of b.pdf p2" in prompt
    assert prompt.endswith("Question: Who?")


def test_sources_are_unique_and_ordered_by_similarity() -> None:
    store = FixedStore(("b.pdf", 0, 0.40), ("a.pdf", 0, 0.90), ("b.pdf", 0, 0.35))

    result = _service(store, FakeLLM()).ask("Question?")

    assert result.sources == ["a.pdf#page=1", "b.pdf#page=1"]


def test_source_label_uses_one_based_pdf_page_fragment() -> None:
    (retrieved,) = FixedStore(("company_memo.pdf", 0, 0.5)).results

    assert source_label(retrieved) == "company_memo.pdf#page=1"


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
def test_blank_question_is_rejected(question: str) -> None:
    with pytest.raises(InvalidRequest):
        _service(FixedStore(), FakeLLM()).ask(question)


def test_llm_failure_propagates_as_upstream_unavailable() -> None:
    class DownLLM(FakeLLM):
        def complete(self, system: str, user: str) -> str:
            raise UpstreamUnavailable("The language model is unavailable: timed out")

    with pytest.raises(UpstreamUnavailable):
        _service(FixedStore(("a.pdf", 0, 0.9)), DownLLM()).ask("Who?")


def test_context_floor_above_gate_is_rejected() -> None:
    with pytest.raises(ValueError):
        AskService(
            FakeEmbedder(),
            FixedStore(),
            FakeLLM(),
            top_k=5,
            min_similarity=0.3,
            context_min_similarity=0.4,
        )


def test_log_has_scores_for_calibration_but_not_the_question() -> None:
    store = FixedStore(("a.pdf", 0, 0.9))

    with capture_logs() as logs:
        _service(store, FakeLLM()).ask("Who is Kevin O'Brien?")

    (done,) = [e for e in logs if e["event"] == "ask_complete"]
    assert done["similarities"] == [0.9]
    assert done["llm_called"] is True
    assert "Brien" not in str(logs)
