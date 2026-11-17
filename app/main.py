"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.extract import router as extract_router
from app.api.extraction_preview import router as preview_router
from app.api.rag import router as rag_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.request_limits import ExtractionBodyLimitMiddleware
from app.models.schemas import HealthResponse
from app.services.ner_async import NERService
from app.services.ocr_service import OCRService
from app.services.ingestion_service import IngestionService
from app.services.extraction_preview import LatestExtractionPreview
from app.services.ask_retrieval import ManagedRetrievalService
from app.services.answer_generator import HTTPAnswerGenerator

settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI):
    configure_logging(settings.log_level)
    application.state.ocr_service = OCRService(settings)
    application.state.ner_service = NERService(settings)
    application.state.ingestion_service = IngestionService(application.state.ocr_service, settings)
    application.state.retrieval_service = ManagedRetrievalService(settings, application.state.ingestion_service.ledger)
    application.state.answer_generator = HTTPAnswerGenerator(settings) if settings.llm_provider != "disabled" else None
    application.state.extraction_preview_store = (
        LatestExtractionPreview(settings.extract_preview_token.get_secret_value())
        if settings.extract_preview_enabled else None
    )
    try:
        yield
    finally:
        if application.state.extraction_preview_store is not None:
            application.state.extraction_preview_store.close()
        try:
            await application.state.retrieval_service.aclose()
        finally:
            try:
                if application.state.answer_generator is not None:
                    await application.state.answer_generator.aclose()
            finally:
                try:
                    await application.state.ingestion_service.aclose()
                finally:
                    try:
                        await application.state.ner_service.aclose()
                    finally:
                        await application.state.ocr_service.aclose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    ExtractionBodyLimitMiddleware, max_request_bytes=settings.max_request_bytes,
    max_in_flight=settings.extract_max_in_flight,
    upload_timeout_seconds=settings.extract_upload_timeout_seconds,
)
app.add_middleware(
    ExtractionBodyLimitMiddleware, max_request_bytes=settings.max_request_bytes,
    max_in_flight=settings.ingest_max_in_flight,
    upload_timeout_seconds=settings.ingest_upload_timeout_seconds, path="/api/ingest",
)
app.add_middleware(
    ExtractionBodyLimitMiddleware, max_request_bytes=settings.ask_max_request_bytes,
    max_in_flight=settings.ask_max_in_flight,
    upload_timeout_seconds=settings.ask_upload_timeout_seconds, path="/api/ask",
)

app.include_router(extract_router, prefix="/api", tags=["extraction"])
app.include_router(preview_router, prefix="/api", tags=["extraction-preview"])
app.include_router(rag_router, prefix="/api", tags=["rag"])


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report application liveness independently of external services."""
    return HealthResponse(status="ok")
