"""Centralized, environment-overridable application settings."""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings used by the application and its infrastructure adapters."""

    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    app_name: str = "Document Intelligence Service"
    app_env: str = "development"
    log_level: str = "INFO"
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = Field(default="documents", min_length=1)
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    # Includes the PDF, form fields, multipart boundaries and part headers.
    max_request_bytes: int = Field(default=21 * 1024 * 1024, gt=0)
    max_names_bytes: int = Field(default=64 * 1024, gt=0)
    max_names_count: int = Field(default=1000, gt=0)
    max_name_chars: int = Field(default=512, gt=0)
    fuzzy_threshold: float = Field(default=0.90, ge=0.0, le=1.0, allow_inf_nan=False)
    extract_max_in_flight: int = Field(default=2, gt=0)
    extract_upload_timeout_seconds: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    extract_preview_enabled: bool = False
    extract_preview_token: SecretStr | None = None
    max_extracted_names: int = Field(default=1000, gt=0)
    max_fuzzy_comparisons: int = Field(default=100_000, gt=0)
    max_fuzzy_work_units: int = Field(default=100_000_000, gt=0)
    ner_model: str = Field(default="en_core_web_sm", min_length=1)
    ner_name_recovery_passes: int = Field(default=0, ge=0, le=3)
    ner_max_page_chars: int = Field(default=100_000, gt=0, le=1_000_000)
    ner_max_document_chars: int = Field(default=1_000_000, gt=0)
    ner_max_concurrent_jobs: int = Field(default=1, gt=0)
    ner_max_queued_jobs: int = Field(default=1, ge=0)
    ner_queue_timeout_seconds: float = Field(default=10.0, gt=0, allow_inf_nan=False)
    ner_job_timeout_seconds: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    ner_shutdown_timeout_seconds: float = Field(default=10.0, gt=0, allow_inf_nan=False)
    max_pdf_pages: int = Field(default=100, gt=0)
    max_page_pixels: int = Field(default=20_000_000, gt=0)
    ocr_dpi: int = Field(default=200, ge=72, le=600)
    ocr_languages: str = Field(default="eng", min_length=1)
    ocr_timeout_seconds: float = Field(default=60.0, gt=0)
    ocr_max_concurrent_jobs: int = Field(default=2, gt=0)
    ocr_max_queued_jobs: int = Field(default=2, ge=0)
    ocr_queue_timeout_seconds: float = Field(default=10.0, gt=0)
    ocr_upload_timeout_seconds: float = Field(default=30.0, gt=0)
    ocr_document_timeout_seconds: float = Field(default=180.0, gt=0)
    ocr_shutdown_timeout_seconds: float = Field(default=10.0, gt=0)
    ocr_orientation_min_confidence: float = Field(default=80.0, ge=0, le=100)
    embedding_model_dir: str = Field(default="/opt/models/all-minilm-l6-v2", min_length=1)
    embedding_query_max_tokens: int = Field(default=256, gt=2, le=256)
    embedding_batch_size: int = Field(default=16, gt=0, le=128)
    embedding_job_timeout_seconds: float = Field(default=120, gt=0, allow_inf_nan=False)
    ingestion_ledger_path: str = Field(default="/app/data/ingestion/ledger.sqlite3", min_length=1)
    ingest_collection: str = Field(default="documents_minilm_1110a243_v1", min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    ingest_max_in_flight: int = Field(default=1, gt=0)
    ingest_upload_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    ingest_job_timeout_seconds: float = Field(default=420, gt=0, allow_inf_nan=False)
    ingest_max_chunks: int = Field(default=1000, gt=0, le=10000)
    ingest_max_page_chars: int = Field(default=100_000, gt=0)
    ingest_max_document_chars: int = Field(default=1_000_000, gt=0)
    ingest_chunk_tokens: int = Field(default=128, gt=2, le=256)
    ingest_overlap_tokens: int = Field(default=32, ge=0)
    qdrant_timeout_seconds: int = Field(default=10, gt=0, le=120)
    qdrant_read_retries: int = Field(default=2, ge=0, le=5)
    qdrant_batch_size: int = Field(default=64, gt=0, le=256)
    ask_max_candidates: int = Field(default=100, ge=1, le=1000)
    ask_max_request_bytes: int = Field(default=16384, gt=0, le=1048576)
    ask_max_in_flight: int = Field(default=2, gt=0, le=100)
    ask_upload_timeout_seconds: float = Field(default=10, gt=0, allow_inf_nan=False)
    ask_job_timeout_seconds: float = Field(default=120, gt=0, allow_inf_nan=False)
    llm_provider: Literal["disabled", "gemini", "openai"] = "disabled"
    llm_model: str = Field(default="", max_length=120)
    llm_api_key: SecretStr | None = None
    llm_allow_external: bool = False
    llm_openai_base_url: str = Field(default="https://api.openai.com/v1", min_length=1, max_length=2048)
    llm_timeout_seconds: float = Field(default=45, gt=0, le=300, allow_inf_nan=False)
    llm_max_output_tokens: int = Field(default=512, ge=32, le=2048)
    llm_max_retries: int = Field(default=1, ge=0, le=3)
    llm_retry_backoff_seconds: float = Field(default=0.25, ge=0, le=5, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_ingestion_limits(self):
        if self.ingest_overlap_tokens >= self.ingest_chunk_tokens - 2:
            raise ValueError("Ingestion overlap leaves no room for content")
        if self.ingest_max_page_chars > self.ingest_max_document_chars:
            raise ValueError("Page character limit exceeds document limit")
        return self

    @model_validator(mode="after")
    def validate_extract_preview(self):
        if self.extract_preview_enabled:
            token = self.extract_preview_token.get_secret_value() if self.extract_preview_token else ""
            if not 32 <= len(token) <= 256 or any(not 33 <= ord(char) <= 126 for char in token):
                raise ValueError("EXTRACT_PREVIEW_TOKEN must contain 32–256 printable non-space ASCII characters")
        return self

    @model_validator(mode="after")
    def validate_llm(self):
        import re

        if self.llm_provider == "disabled":
            return self
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,119}", self.llm_model):
            raise ValueError("An appropriate LLM_MODEL is required")
        if not self.llm_allow_external:
            raise ValueError("External LLM requires LLM_ALLOW_EXTERNAL=true")
        key = self.llm_api_key.get_secret_value() if self.llm_api_key else ""
        if not key or len(key) > 512 or any(not 33 <= ord(c) <= 126 for c in key):
            raise ValueError("A valid LLM_API_KEY is required")
        if self.llm_provider == "openai":
            value = self.llm_openai_base_url
            try:
                url = urlsplit(value)
                host = url.hostname
                valid = (url.scheme == "https" and host and url.username is None and url.password is None
                         and not url.query and not url.fragment and "?" not in value and "#" not in value
                         and "\\" not in value and "%" not in url.netloc
                         and not any(ord(char) <= 32 or ord(char) == 127 for char in value)
                         and url.port != 0)
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("OpenAI base URL must be a valid HTTPS URL without credentials, query or fragment")
        return self

    @field_validator("ner_model")
    @classmethod
    def validate_ner_model(cls, value: str) -> str:
        model = value.strip()
        if not model:
            raise ValueError("NER_MODEL must not be blank")
        return model

    @field_validator("ner_name_recovery_passes", mode="before")
    @classmethod
    def validate_name_recovery_passes(cls, value):
        # Environment variables are strings; reject booleans and fractional
        # values instead of silently coercing them into feature levels.
        if type(value) is int:
            return value
        if isinstance(value, str) and value.strip() in {"0", "1", "2", "3"}:
            return int(value.strip())
        raise ValueError("NER_NAME_RECOVERY_PASSES must be an integer from 0 to 3")

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        level = str(value).upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
        return level


@lru_cache
def get_settings() -> Settings:
    return Settings()
