"""Composition root (AD-1). Constructs adapters once, wires via Depends."""

from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.services.ocr_service import OcrProvider
from app.services.ner_service import NerProvider
from app.services.embedding_service import EmbeddingProvider
from app.services.vector_service import VectorStore
from app.services.rag_service import LLMClient

# Constructed once; rebuilt only if ocr_dpi/ner_model change (not supported in-session)
_ocr: OcrProvider | None = None
_ner: NerProvider | None = None
_embedder: EmbeddingProvider | None = None
_store: VectorStore | None = None
_llm: LLMClient | None = None


def get_ocr(settings: Settings = Depends(get_settings)) -> OcrProvider:
    global _ocr
    if _ocr is None:
        from app.adapters.tesseract_ocr import TesseractOcr
        _ocr = TesseractOcr(settings.ocr_dpi)
    return _ocr


def get_ner(settings: Settings = Depends(get_settings)) -> NerProvider:
    global _ner
    if _ner is None:
        from app.adapters.spacy_ner import SpacyNer
        _ner = SpacyNer(settings.ner_model)
    return _ner


def get_embedding(settings: Settings = Depends(get_settings)) -> EmbeddingProvider:
    global _embedder
    if _embedder is None:
        from app.adapters.sentence_embeddings import Embedder
        _embedder = Embedder(settings.embedding_model)
    return _embedder


def get_vector_store(settings: Settings = Depends(get_settings)) -> VectorStore:
    global _store
    if _store is None:
        from app.adapters.chroma_store import ChromaStore
        _store = ChromaStore(settings.chroma_dir, settings.chroma_collection)
    return _store


def get_llm(settings: Settings = Depends(get_settings)) -> LLMClient:
    global _llm
    if _llm is None:
        from app.adapters.langchain_llm import LangChainLlm
        _llm = LangChainLlm(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
            backoff_seconds=settings.llm_backoff_seconds,
            temperature=settings.llm_temperature,
        )
    return _llm


@asynccontextmanager
async def lifespan(app):
    settings = get_settings()
    # Load spaCy model once at startup (fail fast if missing)
    get_ner(settings)
    # Load embedding model and create store at startup (fail fast)
    get_embedding(settings)
    get_vector_store(settings)
    # LLM is lazy — constructed only when first /api/ask arrives
    yield
