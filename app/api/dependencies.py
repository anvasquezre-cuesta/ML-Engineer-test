"""FastAPI dependencies shared by API routers."""

from fastapi import Request

from app.services.ner_async import NERService
from app.services.ocr_service import OCRService
from app.services.extraction_service import ExtractionService
from app.core.config import get_settings
from app.services.ingestion_service import IngestionService
from app.services.ask_retrieval import ManagedRetrievalService
from app.services.ask_service import AskService


def get_ocr_service(request: Request) -> OCRService:
    """Return the service created once during this application's lifespan."""
    return request.app.state.ocr_service


def get_ner_service(request: Request) -> NERService:
    """Return the lazy worker pool created during the application's lifespan."""
    return request.app.state.ner_service


def get_extraction_service(request: Request) -> ExtractionService:
    """Combine the lifespan-managed OCR and NER services for one request."""
    return ExtractionService(
        get_ocr_service(request), get_ner_service(request), get_settings(),
        preview_store=getattr(request.app.state, "extraction_preview_store", None),
    )


def get_ingestion_service(request: Request) -> IngestionService:
    return request.app.state.ingestion_service


def get_retrieval_service(request: Request) -> ManagedRetrievalService:
    return request.app.state.retrieval_service


def get_ask_service(request: Request) -> AskService | None:
    generator = getattr(request.app.state, "answer_generator", None)
    if generator is None:
        return None
    return AskService(request.app.state.ingestion_service.embeddings,
                      get_retrieval_service(request), generator,
                      max_fragments=min(5, get_settings().ask_max_candidates))
