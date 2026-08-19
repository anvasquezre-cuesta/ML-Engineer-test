"""Centralized, environment-overridable application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for the API and document-extraction pipeline."""

    app_name: str = "Document Intelligence Service"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str | None = Field(
        default=None,
        description="PostgreSQL connection URL used by the RAG persistence layer",
    )
    vector_store_table_name: str = Field(
        default="document_chunks",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )
    vector_store_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    vector_store_statement_timeout_ms: int = Field(default=10_000, ge=100)
    vector_store_max_retries: int = Field(default=2, ge=0, le=10)
    vector_store_retry_delay_seconds: float = Field(default=0.25, ge=0, le=10)
    retrieval_candidate_count: int = Field(default=10, ge=1, le=100)
    reranker_model_name: str = Field(
        default="ms-marco-MiniLM-L-12-v2",
        min_length=1,
    )
    reranker_cache_dir: str = Field(default=".cache/flashrank", min_length=1)
    reranker_max_length: int = Field(default=512, ge=32, le=8_192)
    selected_candidate_count: int = Field(default=5, ge=3, le=5)

    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OPENAI_API_KEY",
            "DOC_INTEL_OPENAI_API_KEY",
        ),
        description="OpenAI API key used to generate document embeddings",
    )
    openai_base_url: str | None = Field(default=None)
    embedding_model_name: str = Field(
        default="text-embedding-3-small",
        min_length=1,
    )
    embedding_dimensions: int = Field(default=1_536, gt=0)
    embedding_batch_size: int = Field(default=64, ge=1, le=1_000)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0)
    embedding_max_retries: int = Field(default=2, ge=0, le=10)

    max_upload_size_mb: int = Field(default=20, gt=0)
    max_names_per_request: int = Field(default=1_000, gt=0)

    ocr_dpi: int = Field(default=300, ge=72, le=600)
    ocr_language: str = Field(default="eng", min_length=1)
    ocr_timeout_seconds: float = Field(default=60.0, gt=0)
    ocr_min_confidence: float = Field(default=0.30, ge=0, le=1)

    ner_model_name: str = Field(default="en_core_web_sm", min_length=1)
    fuzzy_match_threshold: float = Field(default=0.90, ge=0, le=1)
    bbox_match_threshold: float = Field(default=0.80, ge=0, le=1)
    bbox_max_horizontal_gap_factor: float = Field(default=3.0, gt=0)

    structure_max_heading_words: int = Field(default=12, ge=1, le=30)
    chunk_max_words: int = Field(default=300, ge=50, le=2_000)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DOC_INTEL_",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def max_upload_size_bytes(self) -> int:
        """Maximum upload size converted to bytes for request validation."""

        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Load settings once and reuse them across the application."""

    return Settings()
