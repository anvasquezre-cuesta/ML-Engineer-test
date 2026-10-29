"""RAG answer eval (TRD §1, §11; rag/T-006): pass^3 against the live LLM.

Ingests the sample PDFs into a temporary store, then asks every golden question
``--runs`` times (default 3) through the real `AnswerQuestion`, pausing between LLM
calls to stay under the provider's rate limit. An item passes only if it passes every
run (pass^k measures consistency, not luck):

- answerable: the expected fact (normalized) is in the answer and an expected
  ``"{file}, page {n}"`` is in ``sources``;
- unanswerable and injection: the answer is the fixed not-found sentence.

Every run also checks grounding: each returned source belongs to a chunk retrieved for
that question. Exits 0 if at least 80 % of the items pass and grounding is 100 %.
Skips (exit 0) when no ``DOCINTEL_LLM_API_KEY`` is configured.

Usage: ``uv run python scripts/eval_answers.py [--runs 3] [--delay-seconds 2.5]``
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import TypedDict

from app.application.answer_question import AnswerQuestion
from app.application.ingest_document import IngestDocument
from app.application.retrieve_chunks import RetrieveChunks
from app.domain.grounding import NOT_FOUND_ANSWER
from app.domain.names import normalize_name
from app.infrastructure.chroma_vector_store import ChromaVectorStore
from app.infrastructure.cross_encoder_reranker import CrossEncoderReranker
from app.infrastructure.openai_answer_generator import OpenAiCompatibleAnswerGenerator
from app.infrastructure.pymupdf_rasterizer import PyMuPdfRasterizer
from app.infrastructure.sentence_transformer_embedder import SentenceTransformerEmbedder
from app.infrastructure.settings import load_settings
from app.infrastructure.tesseract_ocr import TesseractOcrEngine

ROOT = Path(__file__).parents[1]
GOLDEN = ROOT / "tests" / "golden" / "questions.json"
SAMPLES = ROOT / "sample_pdfs"
MIN_PASS_RATE = 0.80


class GoldenQuestion(TypedDict, total=False):
    id: str
    kind: str
    question: str
    expected_sources: list[str]
    fact: str


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--delay-seconds", type=float, default=2.5)
    args = parser.parse_args()

    settings = load_settings()
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    if not api_key:
        print("SKIPPED: set DOCINTEL_LLM_API_KEY to run the answer eval against the LLM.")
        return 0
    questions: list[GoldenQuestion] = json.loads(GOLDEN.read_text(encoding="utf-8"))["questions"]
    rasterizer = PyMuPdfRasterizer()
    ocr = TesseractOcrEngine(
        settings.ocr_languages,
        settings.ocr_confidence_floor,
        settings.ocr_timeout_seconds,
        settings.tesseract_cmd,
    )
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    generator = OpenAiCompatibleAnswerGenerator(
        settings.llm_base_url,
        api_key,
        settings.llm_model,
        settings.llm_timeout_seconds,
        settings.llm_max_retries,
    )

    passed_items, ungrounded = 0, 0
    # Windows can hold Chroma's sqlite file a moment after close(); a leftover temp
    # folder must not turn a finished eval into a crash.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        store = ChromaVectorStore(folder, settings.vector_store_collection)
        try:
            ingest = IngestDocument(
                rasterizer, ocr, embedder, store, settings.render_dpi, settings.chunk_max_tokens
            )
            for pdf in sorted(SAMPLES.glob("*.pdf")):
                ingest.execute(pdf.read_bytes(), pdf.name)
            retrieve = RetrieveChunks(
                embedder,
                store,
                CrossEncoderReranker(settings.reranker_model),
                settings.retrieval_candidates,
                settings.top_k,
            )
            answer_question = AnswerQuestion(retrieve, generator)

            for question in questions:
                retrieved = {
                    scored.chunk.source for scored in retrieve.execute(question["question"])
                }
                outcomes = []
                for _ in range(args.runs):
                    answer = answer_question.execute(question["question"])
                    ungrounded += not set(answer.sources) <= retrieved
                    outcomes.append(_passes(question, answer.text, answer.sources))
                    time.sleep(args.delay_seconds)
                passed_items += all(outcomes)
                marks = "".join("✓" if ok else "✗" for ok in outcomes)
                print(f"{question['id']} {question['kind']:12} {marks}  {answer.text[:70]!r}")
        finally:
            store.close()

    rate = passed_items / len(questions)
    print(f"\npass^{args.runs}: {passed_items}/{len(questions)} = {rate:.2f} (min {MIN_PASS_RATE})")
    print(f"ungrounded sources: {ungrounded} (must be 0)")
    return 0 if rate >= MIN_PASS_RATE and ungrounded == 0 else 1


def _passes(question: GoldenQuestion, text: str, sources: tuple[str, ...]) -> bool:
    if question["kind"] != "answerable":
        return text == NOT_FOUND_ANSWER
    fact = normalize_name(question["fact"])
    return fact in normalize_name(text) and bool(set(question["expected_sources"]) & set(sources))


if __name__ == "__main__":
    sys.exit(main())
