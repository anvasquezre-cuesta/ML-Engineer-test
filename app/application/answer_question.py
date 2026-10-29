"""Answer-question use case: retrieve → (gate) → LLM → grounded sources (TRD §2, ADR-006).

The LLM composes the answer and nothing else: what is retrieved, whether the LLM is
called at all, and which file/page each citation means are decided by code.
"""

import logging
from dataclasses import dataclass
from time import perf_counter

from app.application.ports import AnswerGenerator
from app.application.retrieve_chunks import RetrieveChunks
from app.domain.grounding import NOT_FOUND_ANSWER, build_prompt, ground_answer

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Answer:
    """The answer text and the ``"{file}, page {n}"`` sources it is grounded in."""

    text: str
    sources: tuple[str, ...]


class AnswerQuestion:
    """Answer any question from the ingested documents, citing file and page."""

    def __init__(self, retrieve: RetrieveChunks, generator: AnswerGenerator) -> None:
        self._retrieve = retrieve
        self._generator = generator

    def execute(self, question: str) -> Answer:
        """Not-found without calling the LLM when nothing relevant was retrieved."""
        retrieved = self._retrieve.execute(question)
        if not retrieved:
            logger.info("answer_completed", extra={"outcome": "not_found", "passages_sent": 0})
            return Answer(NOT_FOUND_ANSWER, ())

        chunks = [scored.chunk for scored in retrieved]
        prompt = build_prompt(question, [chunk.text for chunk in chunks])
        started = perf_counter()
        reply = self._generator.generate(prompt)
        llm_ms = round((perf_counter() - started) * 1000, 1)
        grounded = ground_answer(reply.text, chunks)

        logger.info(
            "answer_completed",
            extra={
                "outcome": "answered" if grounded.sources else "not_found",
                "passages_sent": len(chunks),
                "sources_count": len(grounded.sources),
                "invalid_citations": grounded.invalid_citations,
                "llm_ms": llm_ms,
                "prompt_tokens": reply.prompt_tokens,
                "completion_tokens": reply.completion_tokens,
                "model": reply.model,
            },
        )
        return Answer(grounded.text, grounded.sources)
