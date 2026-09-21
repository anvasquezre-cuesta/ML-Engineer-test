"""
Module: app.dependencies
Path: app/dependencies.py
Description: FastAPI dependency providers for application services.
"""

from functools import lru_cache

import spacy

from app.config import Settings
from app.services.bbox_service import BoundingBoxService
from app.services.embedding_service import EmbeddingService
from app.services.extraction_service import ExtractionService
from app.services.fuzzy_service import FuzzyMatchService
from app.services.ingestion_service import IngestionService
from app.services.llm_provider import (
    LLMProvider,
    OllamaLLMProvider,
    OpenAICompatibleLLMProvider,
)
from app.services.ner_service import NERService
from app.services.ocr_service import OCRService
from app.services.pdf_upload_service import PDFUploadService
from app.services.rag_service import RAGService
from app.services.text_chunker import TextChunker
from app.services.vector_service import VectorStoreService


@lru_cache
def get_settings() -> Settings:
    """Provide the application settings."""
    return Settings()


@lru_cache
def get_ocr_service() -> OCRService:
    """Provide the OCR service."""
    return OCRService(get_settings())


@lru_cache
def get_pdf_upload_service() -> PDFUploadService:
    """Provide the PDF upload service."""
    return PDFUploadService(get_settings())


@lru_cache
def get_fuzzy_match_service() -> FuzzyMatchService:
    """Provide the fuzzy matching service."""
    return FuzzyMatchService(get_settings())


@lru_cache
def get_extraction_service() -> ExtractionService:
    """Provide the document extraction service."""
    settings = get_settings()
    nlp = spacy.load(settings.ner_model)
    ner_service = NERService(nlp)
    bbox_service = BoundingBoxService()
    fuzzy_match_service = get_fuzzy_match_service()

    return ExtractionService(
        ner_service=ner_service,
        bbox_service=bbox_service,
        fuzzy_match_service=fuzzy_match_service,
    )


@lru_cache
def get_embedding_service() -> EmbeddingService:
    """Provide the embedding service."""
    return EmbeddingService(get_settings())


@lru_cache
def get_text_chunker() -> TextChunker:
    """Provide the text chunking service."""
    return TextChunker(get_settings())


@lru_cache
def get_vector_store_service() -> VectorStoreService:
    """Provide the vector-store service."""
    return VectorStoreService(
        settings=get_settings(),
        embedding_service=get_embedding_service(),
    )


@lru_cache
def get_ingestion_service() -> IngestionService:
    """Provide the document ingestion service."""
    return IngestionService(
        ocr_service=get_ocr_service(),
        text_chunker=get_text_chunker(),
        vector_store_service=get_vector_store_service(),
    )


@lru_cache
def get_llm_provider() -> LLMProvider:
    """Provide the configured LLM provider."""
    settings = get_settings()
    provider = settings.llm_provider.casefold()

    if provider == "ollama":
        return OllamaLLMProvider(settings)

    if provider in {"openai", "openai_compatible"}:
        return OpenAICompatibleLLMProvider(settings)

    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")


@lru_cache
def get_rag_service() -> RAGService:
    """Provide the RAG application service."""
    settings = get_settings()

    return RAGService(
        vector_store_service=get_vector_store_service(),
        llm_provider=get_llm_provider(),
        top_k=settings.rag_top_k,
        llm_provider_name=settings.llm_provider,
        llm_model=settings.llm_model,
    )
