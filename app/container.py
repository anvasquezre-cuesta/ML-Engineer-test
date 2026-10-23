"""Composition root: the only place that chooses concrete adapters.

``build_services`` runs once in the app lifespan, so models load at startup,
not per request. Tests pass their own factory to ``create_app`` and get the
same wiring with fakes.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.adapters.chroma_store import ChromaVectorStore
from app.adapters.fuzzy_matcher import FuzzyMatcher
from app.adapters.openai_llm import OpenAICompatibleLLM
from app.adapters.pymupdf_renderer import PyMuPDFRenderer
from app.adapters.qdrant_store import QdrantVectorStore
from app.adapters.sentence_embedder import SentenceTransformerEmbedder
from app.adapters.spacy_ner import SpacyNER
from app.adapters.tesseract_ocr import TesseractOCR
from app.core.config import RAGSettings, Settings
from app.domain.protocols import VectorStore
from app.services.ask import AskService
from app.services.chunking import WordWindowChunker
from app.services.documents import DocumentLoader
from app.services.extraction import ExtractionService
from app.services.health import Check, ReadinessService
from app.services.ingestion import IngestionService
from app.services.names import NameExtractor
from app.services.ocr import OcrService


@dataclass(frozen=True, slots=True)
class Services:
    extraction: ExtractionService
    ingestion: IngestionService
    ask: AskService
    readiness: ReadinessService


ServicesFactory = Callable[[Settings], Services]


def build_vector_store(rag: RAGSettings) -> VectorStore:
    """The one place the store is chosen; services only see the Protocol."""
    if rag.vector_store == "qdrant":
        return QdrantVectorStore.from_settings(rag)
    return ChromaVectorStore.persistent(rag)


def build_services(settings: Settings) -> Services:
    renderer = PyMuPDFRenderer()
    loader = DocumentLoader(
        renderer,
        max_bytes=settings.limits.max_upload_bytes,
        max_pages=settings.limits.max_pages,
    )
    tesseract = TesseractOCR(settings.ocr)
    ocr = OcrService(renderer, tesseract, dpi=settings.ocr.dpi)

    names = NameExtractor(SpacyNER(settings.ner))
    matcher = FuzzyMatcher(threshold=settings.matching.threshold)

    chunker = WordWindowChunker(settings.rag.chunk_words, settings.rag.overlap_words)
    embedder = SentenceTransformerEmbedder(settings.rag)
    store = build_vector_store(settings.rag)
    llm = OpenAICompatibleLLM(settings.llm)

    return Services(
        extraction=ExtractionService(loader, ocr, names, matcher),
        ingestion=IngestionService(loader, ocr, chunker, embedder, store),
        ask=AskService(
            embedder,
            store,
            llm,
            top_k=settings.rag.top_k,
            min_similarity=settings.rag.min_similarity,
            context_min_similarity=settings.rag.context_min_similarity,
        ),
        readiness=ReadinessService(
            [
                Check("ocr", tesseract.version),
                Check(
                    "vector_store",
                    lambda: f"{settings.rag.vector_store}: {store.count()} chunks stored",
                ),
                # Loaded in this function: if either failed, the app would not have started.
                Check("ner_model", lambda: f"{settings.ner.model} loaded"),
                Check("embedding_model", lambda: f"{settings.rag.embedding_model} loaded"),
                Check("llm", llm.ping, critical=False),  # only /api/ask needs it
            ]
        ),
    )
