"""Typed, environment-driven configuration (CONSTITUTION §6).

Every tunable value lives here with a safe default; env vars use the ``DOCINTEL_`` prefix
and a ``.env`` file is honoured. Read once at startup by the composition root.
"""

from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.errors import InfrastructureError

ENV_PREFIX = "DOCINTEL_"
DEFAULT_ENV_FILE = ".env"
EMBEDDER_MAX_TOKENS = 512


class ConfigurationInvalid(InfrastructureError):
    """A configuration value violates its constraints; the service must not start."""

    code = "configuration_invalid"


class Settings(BaseSettings):
    """Service configuration; invalid values fail at startup naming the key."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX, env_file=DEFAULT_ENV_FILE, extra="ignore"
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_pages: int = Field(default=50, gt=0)
    render_dpi: int = Field(default=300, ge=72, le=600)
    ocr_languages: str = Field(default="eng", min_length=1)
    ocr_confidence_floor: float = Field(default=30.0, ge=0.0, le=100.0)
    ocr_timeout_seconds: float = Field(default=60.0, gt=0.0)
    tesseract_cmd: str | None = None
    ner_model: str = Field(default="en_core_web_lg", min_length=1)  # ADR-013
    fuzzy_threshold: float = Field(default=0.90, ge=0.0, le=1.0)
    # RAG (ADR-008, ADR-009, ADR-015)
    embedding_model: str = Field(default="intfloat/multilingual-e5-small", min_length=1)
    # Below e5's 512-token window: anything past it would be silently ignored (ADR-015).
    chunk_max_tokens: int = Field(default=250, gt=0, lt=EMBEDDER_MAX_TOKENS)
    vector_store_path: str = Field(default=".chroma", min_length=1)
    vector_store_collection: str = Field(default="chunks", min_length=3)  # Chroma's minimum
    # Multilingual cross-encoder chosen by spike S6 on CPU (ADR-014).
    reranker_model: str = Field(default="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", min_length=1)
    retrieval_candidates: int = Field(default=10, gt=0)  # per search: dense and BM25 each
    top_k: int = Field(default=5, gt=0)  # chunks sent to the LLM, which decides "not found"
    # LLM: any OpenAI-compatible endpoint; Groq by default (ADR-010)
    llm_base_url: str = Field(default="https://api.groq.com/openai/v1", min_length=1)
    llm_api_key: SecretStr | None = None
    llm_model: str = Field(default="openai/gpt-oss-120b", min_length=1)
    llm_timeout_seconds: float = Field(default=30.0, gt=0.0)
    llm_max_retries: int = Field(default=2, ge=0)


def load_settings(env_file: str | None = DEFAULT_ENV_FILE) -> Settings:
    """Load settings, reporting invalid values by their environment variable name."""
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        problems = "; ".join(
            f"{ENV_PREFIX}{str(error['loc'][0]).upper()}: {error['msg']}" for error in exc.errors()
        )
        raise ConfigurationInvalid(f"Invalid configuration: {problems}") from exc
