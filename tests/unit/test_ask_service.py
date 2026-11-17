import asyncio

import pytest

from app.services.ask_service import (
    AnswerGenerationError, AskService, CitationEvidence, GeneratedAnswer, NO_EVIDENCE, RetrievedFragment,
)


class Embedder:
    async def embed_query(self, question):
        self.question = question
        return [1.0]


class Retriever:
    def __init__(self, fragments):
        self.fragments = fragments

    async def retrieve(self, vector, *, limit):
        assert vector == [1.0]
        return self.fragments


class Generator:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def generate(self, question, context):
        self.calls.append((question, context))
        return self.result


def run(fragments, result, **settings):
    embedder, generator = Embedder(), Generator(result)
    answer = asyncio.run(AskService(embedder, Retriever(fragments), generator, **settings).ask(" question "))
    return answer, embedder, generator


def test_no_context_never_calls_generator():
    answer, embedder, generator = run([], None)
    assert answer.answer == NO_EVIDENCE and answer.sources == ()
    assert embedder.question == "question" and not generator.calls


def test_sources_are_selected_only_from_valid_citations_and_deduplicated():
    fragments = [RetrievedFragment("First", "one.pdf page 1"), RetrievedFragment("Second", "two.pdf page 2")]
    answer, _, generator = run(fragments, GeneratedAnswer(" answer ", (
        CitationEvidence("S2", "Second"), CitationEvidence("S1", "First"), CitationEvidence("S2", "Second"),
    )))
    assert answer.answer == "answer" and answer.sources == ("two.pdf page 2", "one.pdf page 1")
    assert [part.citation_id for part in generator.calls[0][1]] == ["S1", "S2"]


def test_generator_without_citations_must_abstain():
    answer, _, _ = run([RetrievedFragment("text", "source")], GeneratedAnswer("unsupported", ()))
    assert answer.answer == NO_EVIDENCE and not answer.sources


@pytest.mark.parametrize("result", [GeneratedAnswer("answer", (CitationEvidence("S2", "text"),)),
                                    GeneratedAnswer("", (CitationEvidence("S1", "text"),)), None])
def test_invalid_generator_results_fail_closed(result):
    with pytest.raises(AnswerGenerationError):
        run([RetrievedFragment("text", "source")], result)


def test_context_is_bounded_without_truncation():
    fragments = [RetrievedFragment("123", "one"), RetrievedFragment("4567", "two")]
    answer, _, generator = run(fragments, GeneratedAnswer("answer", (CitationEvidence("S1", "123"),)), max_context_chars=5)
    assert answer.sources == ("one",) and len(generator.calls[0][1]) == 1


def test_oversized_first_fragment_has_no_evidence_and_no_generator_call():
    answer, _, generator = run([RetrievedFragment("123456", "one")], None, max_context_chars=5)
    assert answer.answer == NO_EVIDENCE and not generator.calls


def test_invalid_retrieval_is_rejected_without_exposing_text():
    with pytest.raises(AnswerGenerationError, match="^Invalid retrieval result$"):
        run([RetrievedFragment("secret", "")], None)


@pytest.mark.parametrize("citation", [
    CitationEvidence("S1", "invented"), CitationEvidence("S1", ""), CitationEvidence("S1", " "),
    CitationEvidence("S1", "text" * 129), CitationEvidence("S2", "actual text"), "S1",
])
def test_invalid_evidence_rejects_entire_answer_without_retry(citation):
    with pytest.raises(AnswerGenerationError, match="Invalid generated answer or citations"):
        run([RetrievedFragment("actual text", "source")], GeneratedAnswer("answer", (citation,)))


def test_quote_must_match_the_correct_fragment_exactly():
    fragments = [RetrievedFragment("first text", "one"), RetrievedFragment("second text", "two")]
    with pytest.raises(AnswerGenerationError):
        run(fragments, GeneratedAnswer("answer", (CitationEvidence("S1", "second text"),)))
