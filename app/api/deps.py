from fastapi import Request

from app.core.config import Settings, get_settings
from app.services.extraction_service import ExtractionPipeline
from app.services.rag_service import RagService


def settings() -> Settings:
    return get_settings()


def extraction(request: Request) -> ExtractionPipeline:
    return request.app.state.extraction


def rag(request: Request) -> RagService:
    return request.app.state.rag
