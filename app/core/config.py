"""Application settings (AD-2)."""

from pydantic_settings import BaseSettings

_settings = None


class Settings(BaseSettings):
    ocr_dpi: int = 300
    ner_model: str = "en_core_web_sm"
    max_upload_bytes: int = 20_000_000
    fuzzy_match_threshold: int = 90

    # RAG settings
    embedding_model: str = "all-MiniLM-L6-v2"
    chroma_dir: str = ".chroma/"
    chroma_collection: str = "doc_intelligence"
    chunk_size: int = 500
    top_k: int = 5
    llm_base_url: str = "http://127.0.0.1:8787/v1"
    llm_api_key: str = "not-needed"
    llm_model: str = "gpt-4"
    llm_temperature: float = 0.0
    llm_timeout: float = 30.0
    llm_max_retries: int = 3
    llm_backoff_seconds: float = 2.0

    # Static files
    static_dir: str = "static"

    class Config:
        env_prefix = "DIS_"
        extra = "ignore"


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Test seam: drop the cached settings so the next get_settings() re-reads env."""
    global _settings
    _settings = None
