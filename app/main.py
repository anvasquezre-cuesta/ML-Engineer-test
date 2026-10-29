"""App factory and composition root (CONSTITUTION §4.5, ADR-012).

The lifespan is the only place adapters are instantiated; routers receive them through
the providers in ``app/api/dependencies.py``.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import Container
from app.api.errors import register_error_handlers
from app.api.extract import router as extract_router
from app.api.health import router as health_router
from app.api.middleware import RequestIdMiddleware
from app.api.rag import router as rag_router
from app.api.upload import UploadLimits
from app.api.viewer import router as viewer_router
from app.application.answer_question import AnswerQuestion
from app.application.extract_names import ExtractNames
from app.application.ingest_document import IngestDocument
from app.application.retrieve_chunks import RetrieveChunks
from app.infrastructure.chroma_vector_store import ChromaVectorStore
from app.infrastructure.cross_encoder_reranker import CrossEncoderReranker
from app.infrastructure.logging import configure_logging
from app.infrastructure.openai_answer_generator import OpenAiCompatibleAnswerGenerator
from app.infrastructure.pymupdf_rasterizer import PyMuPdfRasterizer
from app.infrastructure.sentence_transformer_embedder import SentenceTransformerEmbedder
from app.infrastructure.settings import Settings, load_settings
from app.infrastructure.spacy_recognizer import SpacyPersonNameRecognizer
from app.infrastructure.tesseract_ocr import TesseractOcrEngine

logger = logging.getLogger(__name__)


def build_container(settings: Settings) -> Container:
    """Build every adapter and use case once, from configuration."""
    rasterizer = PyMuPdfRasterizer()
    ocr = TesseractOcrEngine(
        languages=settings.ocr_languages,
        confidence_floor=settings.ocr_confidence_floor,
        timeout_seconds=settings.ocr_timeout_seconds,
        tesseract_cmd=settings.tesseract_cmd,
    )
    recognizer = SpacyPersonNameRecognizer(settings.ner_model)
    extract_names = ExtractNames(
        rasterizer=rasterizer,
        ocr=ocr,
        recognizer=recognizer,
        dpi=settings.render_dpi,
        fuzzy_threshold=settings.fuzzy_threshold,
    )
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    store = ChromaVectorStore(settings.vector_store_path, settings.vector_store_collection)
    ingest_document = IngestDocument(
        rasterizer=rasterizer,
        ocr=ocr,
        embedder=embedder,
        store=store,
        dpi=settings.render_dpi,
        max_tokens=settings.chunk_max_tokens,
    )
    retrieve = RetrieveChunks(
        embedder=embedder,
        store=store,
        reranker=CrossEncoderReranker(settings.reranker_model),
        candidates=settings.retrieval_candidates,
        top_k=settings.top_k,
    )
    generator = OpenAiCompatibleAnswerGenerator(
        base_url=settings.llm_base_url,
        api_key=_llm_api_key(settings),
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    return Container(
        upload_limits=UploadLimits(settings.max_upload_bytes, settings.max_pages),
        rasterizer=rasterizer,
        extract_names=extract_names,
        ingest_document=ingest_document,
        answer_question=AnswerQuestion(retrieve, generator),
        on_shutdown=(store.close,),
    )


def _llm_api_key(settings: Settings) -> str | None:
    """The configured key, or ``None`` (an empty value counts as missing)."""
    key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    if not key:
        logger.warning("llm_not_configured")  # /ask will answer 503 when it needs the LLM
    return key or None


def create_app(
    settings: Settings | None = None,
    build_container: Callable[[Settings], Container] = build_container,
) -> FastAPI:
    """Create the app; settings load (and fail fast) here, adapters in the lifespan."""
    resolved = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved.log_level)
        container = build_container(resolved)
        app.state.container = container
        logger.info("startup_completed")
        yield
        for release in container.on_shutdown:
            release()

    app = FastAPI(title="Document Intelligence Service", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(health_router, tags=["health"])
    app.include_router(extract_router, prefix="/api", tags=["extraction"])
    app.include_router(rag_router, prefix="/api", tags=["rag"])
    app.include_router(viewer_router)
    return app


app = create_app()
