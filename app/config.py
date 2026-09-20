"""
Module: app.config
Path: app/config.py
Description: Centralized application configuration.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from defaults and environment variables."""

    tesseract_cmd: str | None = None
    ocr_dpi: int = 300
    fuzzy_match_threshold: float = 0.90
    ner_model: str = "en_core_web_sm"

    embedding_model: str = "sentence-transformers/all-mpnet-base-v2"
    chroma_persist_directory: str = "./data/chroma"
    chroma_collection_name: str = "documents"
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 50
    rag_top_k: int = 12

    # LLM settings are provider-neutral. Local development uses Ollama by default.
    # An evaluator can override these through APP_* environment variables.
    #
    # Example evaluator configuration:
    # APP_LLM_PROVIDER=openai
    # APP_LLM_MODEL=<evaluator-selected-model>
    # APP_LLM_BASE_URL=<OpenAI-compatible-endpoint>
    # APP_LLM_API_KEY=<secret-from-environment>
    llm_provider: str = "ollama"
    llm_model: str = "llama3"
    llm_base_url: str = "http://localhost:11434"
    llm_api_key: str | None = None
    llm_temperature: float = 0.0
    llm_timeout: float = 60.0
    llm_max_retries: int = 2

    upload_max_size_mb: int = Field(default=10, gt=0)

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
