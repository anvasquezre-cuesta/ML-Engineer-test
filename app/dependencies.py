"""
Module: app.dependencies
Path: app/dependencies.py
Description: FastAPI dependency providers for application services.
"""

from functools import lru_cache

import spacy

from app.config import Settings
from app.services.bbox_service import BoundingBoxService
from app.services.extraction_service import ExtractionService
from app.services.fuzzy_service import FuzzyMatchService
from app.services.ner_service import NERService
from app.services.ocr_service import OCRService


@lru_cache
def get_settings() -> Settings:
    """Provide the application settings."""

    return Settings()


@lru_cache
def get_ocr_service() -> OCRService:
    """Provide the OCR service."""

    return OCRService(get_settings())


@lru_cache
def get_fuzzy_match_service() -> FuzzyMatchService:
    """Provide the fuzzy matching service."""

    return FuzzyMatchService(get_settings())


@lru_cache
def get_extraction_service() -> ExtractionService:
    """Provide the document extraction service."""

    nlp = spacy.load("en_core_web_sm")

    ner_service = NERService(nlp)
    bbox_service = BoundingBoxService()
    fuzzy_match_service = get_fuzzy_match_service()

    return ExtractionService(
        ner_service=ner_service,
        bbox_service=bbox_service,
        fuzzy_match_service=fuzzy_match_service,
    )
