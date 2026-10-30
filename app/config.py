"""Centralized, environment-overridable settings (read from env vars or `.env`)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OCR (the `tesseract` binary is resolved from PATH)
    ocr_dpi: int = 300
    ocr_lang: str = "eng"
    ocr_psm: int = 3
    ocr_timeout_s: int = 30
    bbox_origin: Literal["top-left", "bottom-left"] = "top-left"

    # Upload limits
    max_upload_mb: int = Field(20, gt=0)
    max_pages: int = Field(50, gt=0)

    # NER
    ner_model: str = "en_core_web_sm"
    ner_drop_all_caps: bool = True

    # Embeddings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"

    # RAG
    chunk_size: int = Field(500, gt=0)
    chunk_overlap: int = Field(60, ge=0)
    chroma_path: str = "data/chroma"
    chroma_collection: str = "documents"
    top_k: int = Field(5, gt=0)
    min_score: float = Field(0.20, ge=0.0, le=1.0)

    # LLM (OpenAI-compatible endpoint; 127.0.0.1 avoids slow IPv6 "localhost")
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = "qwen2.5:7b-instruct"
    llm_api_key: str = ""
    llm_timeout_s: float = Field(60, gt=0)
    llm_connect_timeout_s: float = Field(5, gt=0)
    llm_max_tokens: int = Field(150, gt=0)
    llm_max_attempts: int = Field(3, ge=1)
    llm_retry_max_wait_s: float = Field(8, ge=0)

    # Fuzzy matching
    fuzzy_threshold: float = Field(0.90, ge=0.0, le=1.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
