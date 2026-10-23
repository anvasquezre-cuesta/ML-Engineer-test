"""Centralised, environment-overridable configuration.

Every tunable (DPI, thresholds, model names, hosts, limits) lives here. Nested
groups are overridden with a double underscore, e.g. ``OCR__DPI=200`` or
``RAG__CHUNK_WORDS=120``. Values are read from the environment and from ``.env``.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OCRSettings(BaseModel):
    dpi: int = Field(default=300, ge=72, le=600, description="Render resolution for OCR")
    lang: str = Field(default="eng", description="Tesseract language(s), e.g. 'eng+spa'")
    psm: int = Field(default=3, ge=0, le=13, description="Tesseract page segmentation mode")
    tesseract_cmd: str | None = Field(
        default=None, description="Path to the tesseract binary when it is not on PATH"
    )
    page_timeout_s: float = Field(default=120.0, gt=0, description="Tesseract limit per page")


class NERSettings(BaseModel):
    model: str = Field(default="en_core_web_lg", description="spaCy pipeline name")
    person_labels: tuple[str, ...] = Field(
        default=("PERSON", "PER"), description="Entity labels treated as a person"
    )


class MatchingSettings(BaseModel):
    threshold: float = Field(default=0.90, ge=0.0, le=1.0, description="Minimum similarity")


class RAGSettings(BaseModel):
    chunk_words: int = Field(default=150, ge=1)
    overlap_words: int = Field(default=30, ge=0)
    top_k: int = Field(default=5, ge=1)
    # Placeholder until calibrated on the sample questions (roadmap F9).
    min_similarity: float = Field(default=0.35, ge=0.0, le=1.0)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chroma_path: str = "./data/chroma"
    collection: str = "documents"

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> Self:
        if self.overlap_words >= self.chunk_words:
            raise ValueError("overlap_words must be smaller than chunk_words")
        return self


class LLMSettings(BaseModel):
    base_url: str = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible endpoint
    api_key: SecretStr = SecretStr("ollama")  # Ollama ignores it; the client requires one
    model: str = "llama3.2"
    timeout_s: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class LimitSettings(BaseModel):
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    max_pages: int = Field(default=50, ge=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = Field(default=True, description="JSON logs; false gives console output")

    ocr: OCRSettings = OCRSettings()
    ner: NERSettings = NERSettings()
    matching: MatchingSettings = MatchingSettings()
    rag: RAGSettings = RAGSettings()
    llm: LLMSettings = LLMSettings()
    limits: LimitSettings = LimitSettings()


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings. Tests call ``get_settings.cache_clear()`` after env changes."""
    return Settings()
