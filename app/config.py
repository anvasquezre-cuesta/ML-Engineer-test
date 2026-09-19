"""
Module: app.config
Path: app/config.py
Description: Centralized application configuration.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Define application settings loaded from environment variables."""

    tesseract_cmd: str | None = None
    ocr_dpi: int = 300
    fuzzy_match_threshold: float = 0.90

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
