import logging

import pytest

from app.application.answer_question import Answer, AnswerQuestion
from app.application.retrieve_chunks import RetrieveChunks
from app.domain.chunking import Chunk
from app.domain.errors import LlmNotConfigured
from app.domain.grounding import NOT_FOUND_ANSWER
from tests.fakes import FakeAnswerGenerator, FakeEmbedder, FakeReranker, InMemoryVectorStore

CHUNKS = [
    Chunk("aaa", "company_memo.pdf", 0, 0, "Robert Chen was promoted to Vice President."),
    Chunk("bbb", "meeting_minutes.pdf", 0, 0, "Thomas Muller seconded the motion."),
    Chunk("bbb", "meeting_minutes.pdf", 1, 1, "Migration completes by Q3 2024."),
]
# Retrieval order is decided by these scores: memo, minutes p0, minutes p1.
SCORES = {CHUNKS[0].text: 9.0, CHUNKS[1].text: 5.0, CHUNKS[2].text: 1.0}


def _answer(
    generator: FakeAnswerGenerator,
    scores: dict[str, float] = SCORES,
    chunks: list[Chunk] = CHUNKS,
) -> AnswerQuestion:
    store = InMemoryVectorStore()
    for chunk in chunks:
        store.replace_document(f"{chunk.document_id}-{chunk.chunk_index}", [chunk], [[1.0] * 26])
    retrieve = RetrieveChunks(FakeEmbedder(), store, FakeReranker(scores), candidates=10, top_k=5)
    return AnswerQuestion(retrieve, generator)


def test_sources_are_the_cited_passages_only() -> None:
    generator = FakeAnswerGenerator("Chen was promoted [1]. Muller seconded [3]. Noise [7].")

    answer = _answer(generator).execute("Who was promoted?")

    assert answer == Answer(
        "Chen was promoted [1]. Muller seconded [2]. Noise.",
        ("company_memo.pdf, page 0", "meeting_minutes.pdf, page 1"),
    )
    assert '<passage n="1">\nRobert Chen' in generator.prompts[0].user


def test_an_uncited_reply_becomes_not_found() -> None:
    answer = _answer(FakeAnswerGenerator("Robert Chen, obviously.")).execute("Who was promoted?")

    assert answer == Answer(NOT_FOUND_ANSWER, ())


def test_no_llm_call_when_nothing_is_ingested() -> None:
    generator = FakeAnswerGenerator("should never be used [1].")

    answer = _answer(generator, chunks=[]).execute("What is the parental leave policy?")

    assert answer == Answer(NOT_FOUND_ANSWER, ())
    assert generator.prompts == []


def test_the_llm_decides_when_the_passages_do_not_answer() -> None:
    generator = FakeAnswerGenerator(NOT_FOUND_ANSWER)
    low_scores = {chunk.text: -9.0 for chunk in CHUNKS}

    answer = _answer(generator, scores=low_scores).execute("What is the parental leave policy?")

    assert answer == Answer(NOT_FOUND_ANSWER, ())
    assert len(generator.prompts) == 1  # the passages were sent, however low they scored


def test_llm_errors_propagate() -> None:
    generator = FakeAnswerGenerator(error=LlmNotConfigured("No LLM API key is configured"))

    with pytest.raises(LlmNotConfigured):
        _answer(generator).execute("Who was promoted?")


def test_completion_log_has_counts_but_no_question_or_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    _answer(FakeAnswerGenerator("Chen [1]. Bad [8].")).execute("secret question")

    records = [r for r in caplog.records if r.getMessage() == "answer_completed"]
    assert len(records) == 1
    fields = records[0].__dict__
    assert fields["outcome"] == "answered"
    assert (fields["passages_sent"], fields["sources_count"]) == (3, 1)
    assert fields["invalid_citations"] == 1
    assert (fields["prompt_tokens"], fields["completion_tokens"]) == (100, 10)
    assert fields["model"] == "fake-llm"
    assert "secret question" not in repr(fields)
    assert "Chen" not in repr(fields)
