from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every tunable lives here and can be overridden by an env var of the same name."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # uploads
    max_upload_mb: int = 20
    max_pages: int = 50

    # OCR
    ocr_dpi: int = 300
    ocr_languages: str = "eng"  # tesseract syntax, e.g. "eng+spa"
    ocr_min_confidence: int = 0

    # NER
    ner_model: str = "en_core_web_sm"

    # name matching (0..1)
    fuzzy_threshold: float = 0.90  # extracted name vs requested name
    bbox_token_threshold: float = 0.80  # single OCR word vs single name token

    # RAG
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_size: int = 500  # characters, never splits a word
    chunk_overlap: int = 50
    top_k: int = 5
    chroma_dir: str = "./chroma_data"
    chroma_collection: str = "documents"

    # LLM (any OpenAI-compatible /chat/completions endpoint)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_s: float = 30.0
    llm_max_attempts: int = 3
    # merged into every chat request; e.g. {"chat_template_kwargs": {"enable_thinking": false}}
    # to stop Qwen3 on vLLM from writing its reasoning into the answer
    llm_extra_body: dict[str, Any] = {}

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
