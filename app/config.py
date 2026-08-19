"""Centralized, environment-overridable application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for the API and document-extraction pipeline."""

    app_name: str = "Document Intelligence Service"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str | None = Field(
        default=None,
        description="PostgreSQL connection URL used by the future RAG persistence layer",
    )

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
    )

    @property
    def max_upload_size_bytes(self) -> int:
        """Maximum upload size converted to bytes for request validation."""

        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Load settings once and reuse them across the application."""

    return Settings()
