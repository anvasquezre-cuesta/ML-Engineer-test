"""FastAPI dependency providers: routers get services and settings from here only."""

from typing import cast

from fastapi import Request

from app.container import Services
from app.core.config import Settings
from app.services.ask import AskService
from app.services.extraction import ExtractionService
from app.services.health import ReadinessService
from app.services.ingestion import IngestionService


def get_services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_extraction_service(request: Request) -> ExtractionService:
    return get_services(request).extraction


def get_ingestion_service(request: Request) -> IngestionService:
    return get_services(request).ingestion


def get_ask_service(request: Request) -> AskService:
    return get_services(request).ask


def get_readiness_service(request: Request) -> ReadinessService:
    return get_services(request).readiness
