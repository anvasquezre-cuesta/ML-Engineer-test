"""RAG retrieval eval (TRD §1, §11; rag/T-005).

Ingests the sample PDFs into a temporary vector store exactly as the service does, runs
every golden question through `RetrieveChunks`, and prints per item the top rerank score
and whether an expected page was retrieved. The scores are informative only: there is
no score cut-off, the LLM decides when the passages don't answer (CR-002).

Also prints hit@1: with few, short documents top-k can hold every chunk, so hit@k alone
proves little. Exits 0 only if hit@k is 100 %.

Usage: ``uv run python scripts/eval_retrieval.py``
"""

import json
import math
import sys
import tempfile
from pathlib import Path

from app.application.ingest_document import IngestDocument
from app.application.retrieve_chunks import RetrieveChunks
from app.infrastructure.chroma_vector_store import ChromaVectorStore
from app.infrastructure.cross_encoder_reranker import CrossEncoderReranker
from app.infrastructure.pymupdf_rasterizer import PyMuPdfRasterizer
from app.infrastructure.sentence_transformer_embedder import SentenceTransformerEmbedder
from app.infrastructure.settings import load_settings
from app.infrastructure.tesseract_ocr import TesseractOcrEngine

ROOT = Path(__file__).parents[1]
GOLDEN = ROOT / "tests" / "golden" / "questions.json"
SAMPLES = ROOT / "sample_pdfs"


def main() -> int:
    settings = load_settings()
    questions = json.loads(GOLDEN.read_text(encoding="utf-8"))["questions"]
    rasterizer = PyMuPdfRasterizer()
    ocr = TesseractOcrEngine(
        settings.ocr_languages,
        settings.ocr_confidence_floor,
        settings.ocr_timeout_seconds,
        settings.tesseract_cmd,
    )
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    reranker = CrossEncoderReranker(settings.reranker_model)

    # Windows can hold Chroma's sqlite file a moment after close(); a leftover temp
    # folder must not turn a finished eval into a crash.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        store = ChromaVectorStore(folder, settings.vector_store_collection)
        try:
            ingest = IngestDocument(
                rasterizer, ocr, embedder, store, settings.render_dpi, settings.chunk_max_tokens
            )
            for pdf in sorted(SAMPLES.glob("*.pdf")):
                result = ingest.execute(pdf.read_bytes(), pdf.name)
                print(f"ingested {pdf.name}: {result.chunk_count} chunks")
            retrieve = RetrieveChunks(
                embedder,
                store,
                reranker,
                settings.retrieval_candidates,
                settings.top_k,
            )
            rows = [(q, retrieve.execute(q["question"])) for q in questions]
        finally:
            store.close()

    print(f"\n{'id':4} {'kind':12} {'top score':>9}  hit  retrieved pages")
    hits, firsts, total = 0, 0, 0
    for question, retrieved in rows:
        top = retrieved[0].score if retrieved else -math.inf
        sources = [scored.chunk.source for scored in retrieved]
        hit = ""
        if question["kind"] == "answerable":
            found = any(source in sources for source in question["expected_sources"])
            hits += found
            firsts += bool(sources) and sources[0] in question["expected_sources"]
            hit = "yes" if found else "NO"
            total += 1
        print(f"{question['id']:4} {question['kind']:12} {top:9.3f}  {hit:3}  {sources}")

    print(f"\nhit@{settings.top_k}: {hits}/{total} · hit@1: {firsts}/{total}")
    return 0 if hits == total else 1


if __name__ == "__main__":
    sys.exit(main())
