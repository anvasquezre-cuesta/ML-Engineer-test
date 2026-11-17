"""Provider-independent question answering over a trusted retrieval interface.

The retriever must independently enforce ledger eligibility and return only
validated fragments from completed ingestions.
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.services.ask_input import normalize_question


NO_EVIDENCE = "No hay información suficiente en los documentos para responder."


class AnswerGenerationError(RuntimeError):
    """The generator returned an invalid or unverifiable answer."""


class AnswerEvidenceError(AnswerGenerationError):
    """The generated answer or its citations do not satisfy the contract."""


@dataclass(frozen=True)
class RetrievedFragment:
    text: str = field(repr=False)
    source: str


@dataclass(frozen=True)
class ContextFragment:
    citation_id: str
    text: str = field(repr=False)


@dataclass(frozen=True)
class CitationEvidence:
    citation_id: str
    quote: str = field(repr=False)


@dataclass(frozen=True)
class GeneratedAnswer:
    answer: str = field(repr=False)
    citations: tuple[CitationEvidence, ...]


@dataclass(frozen=True)
class Answer:
    answer: str = field(repr=False)
    sources: tuple[str, ...]


class QueryEmbedder(Protocol):
    async def embed_query(self, question: str) -> list[float]: ...


class EligibleRetriever(Protocol):
    async def retrieve(self, vector: list[float], *, limit: int) -> list[RetrievedFragment]: ...


class AnswerGenerator(Protocol):
    async def generate(self, question: str, context: tuple[ContextFragment, ...]) -> GeneratedAnswer: ...


class AskService:
    def __init__(self, embedder: QueryEmbedder, retriever: EligibleRetriever, generator: AnswerGenerator,
                 *, max_fragments: int = 5, max_context_chars: int = 12000, max_answer_chars: int = 4000):
        if any(type(value) is not int or value <= 0 for value in (max_fragments, max_context_chars, max_answer_chars)):
            raise ValueError("Answer limits must be positive integers")
        self.embedder, self.retriever, self.generator = embedder, retriever, generator
        self.max_fragments, self.max_context_chars, self.max_answer_chars = max_fragments, max_context_chars, max_answer_chars

    async def ask(self, question: str) -> Answer:
        question = normalize_question(question)
        vector = await self.embedder.embed_query(question)
        fragments = await self.retriever.retrieve(vector, limit=self.max_fragments)
        if not isinstance(fragments, list) or len(fragments) > self.max_fragments:
            raise AnswerGenerationError("Invalid retrieval result")
        context, sources, texts, total = [], {}, {}, 0
        for fragment in fragments:
            if (not isinstance(fragment, RetrievedFragment) or not isinstance(fragment.text, str)
                    or not fragment.text.strip() or not isinstance(fragment.source, str)
                    or not fragment.source.strip() or len(fragment.source) > 512):
                raise AnswerGenerationError("Invalid retrieval result")
            # Never truncate a fragment; stop at the first item exceeding the budget.
            if total + len(fragment.text) > self.max_context_chars:
                break
            citation_id = f"S{len(context) + 1}"
            context.append(ContextFragment(citation_id, fragment.text))
            sources[citation_id] = fragment.source
            texts[citation_id] = fragment.text
            total += len(fragment.text)
        if not context:
            return Answer(NO_EVIDENCE, ())
        generated = await self.generator.generate(question, tuple(context))
        if (not isinstance(generated, GeneratedAnswer) or not isinstance(generated.answer, str)
                or not generated.answer.strip() or len(generated.answer) > self.max_answer_chars
                or not isinstance(generated.citations, tuple)
                or any(not isinstance(citation, CitationEvidence) or not isinstance(citation.citation_id, str)
                       or citation.citation_id not in sources or not isinstance(citation.quote, str)
                       or not citation.quote.strip() or len(citation.quote) > 512
                       or citation.quote not in texts[citation.citation_id]
                       for citation in generated.citations)):
            raise AnswerEvidenceError("Invalid generated answer or citations")
        if not generated.citations:
            # An ungrounded answer is never returned as fact.
            return Answer(NO_EVIDENCE, ())
        selected = tuple(dict.fromkeys(sources[citation.citation_id] for citation in generated.citations))
        return Answer(generated.answer.strip(), selected)
