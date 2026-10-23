"""Calibrate ``RAG__MIN_SIMILARITY`` on the sample PDFs.

Ingests the samples into a temporary Chroma directory, embeds questions the
documents answer and questions they do not, and prints the retrieval
similarities. The threshold belongs between the weakest answerable best-match
and the strongest unanswerable best-match.

    uv run python scripts/calibrate_similarity.py
"""

import tempfile
from pathlib import Path

from app.adapters.chroma_store import ChromaVectorStore
from app.adapters.pymupdf_renderer import PyMuPDFRenderer
from app.adapters.sentence_embedder import SentenceTransformerEmbedder
from app.adapters.tesseract_ocr import TesseractOCR
from app.core.config import get_settings
from app.services.ask import source_label
from app.services.chunking import WordWindowChunker
from app.services.documents import DocumentLoader
from app.services.ingestion import IngestionService
from app.services.ocr import OcrService

SAMPLES = Path(__file__).parents[1] / "sample_pdfs"

ANSWERABLE = {
    "Who was promoted to Vice President of Engineering?": "company_memo.pdf#page=1",
    "Who presented the Q4 financial results?": "meeting_minutes.pdf#page=1",
    "When is the next board meeting scheduled?": "meeting_minutes.pdf#page=2",
    "What is the total research budget?": "research_report.pdf#page=2",
    "Who leads the Machine Learning Division?": "research_report.pdf#page=1",
}
UNANSWERABLE = [
    "What is the 2025 marketing budget?",
    "What is the company's current stock price?",
    "How many vacation days do employees get per year?",
    "Who won the football World Cup?",
    "What is the recipe for chocolate cake?",
]


def main() -> None:
    settings = get_settings()
    # Chroma keeps its files open until the process exits; Windows then refuses the delete.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        rag = settings.rag.model_copy(update={"chroma_path": tmp, "collection": "calibration"})
        renderer = PyMuPDFRenderer()
        embedder = SentenceTransformerEmbedder(rag)
        store = ChromaVectorStore.persistent(rag)
        ingestion = IngestionService(
            DocumentLoader(renderer, max_bytes=10**8, max_pages=50),
            OcrService(renderer, TesseractOCR(settings.ocr), dpi=settings.ocr.dpi),
            WordWindowChunker(rag.chunk_words, rag.overlap_words),
            embedder,
            store,
        )
        for pdf in sorted(SAMPLES.glob("*.pdf")):
            ingestion.ingest(pdf.read_bytes(), pdf.name)

        def best(question: str) -> tuple[float, str, list[str]]:
            results = store.query(embedder.embed([question])[0], rag.top_k)
            ranking = [f"{r.similarity:.3f} {source_label(r)}" for r in results]
            return results[0].similarity, source_label(results[0]), ranking

        print("\nANSWERABLE (expected source)")
        answerable = []
        for question, expected in ANSWERABLE.items():
            top, source, ranking = best(question)
            answerable.append(top)
            mark = "ok  " if source == expected else "MISS"
            print(f"  {top:.3f} {mark} expected {expected:28s} {question}")
            print(f"        ranking: {' | '.join(ranking)}")

        print("\nUNANSWERABLE")
        unanswerable = []
        for question in UNANSWERABLE:
            top, _, ranking = best(question)
            unanswerable.append(top)
            print(f"  {top:.3f} {question}")
            print(f"        ranking: {' | '.join(ranking[:3])}")

        low, high = min(answerable), max(unanswerable)
        print(f"\nweakest answerable best match:   {low:.3f}")
        print(f"strongest unanswerable best match: {high:.3f}")
        if low > high:
            print(f"separable; midpoint threshold = {(low + high) / 2:.3f}")
        else:
            print("NOT separable by a single threshold")


if __name__ == "__main__":
    main()
