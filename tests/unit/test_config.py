"""Tests for how settings are read from the environment and .env files."""

from pathlib import Path

from pydantic import BaseModel
from pydantic import ValidationError
import pytest

from app.config import Settings

ENV_EXAMPLE = Path(__file__).parents[2] / ".env.example"


def _setting_env_names() -> set[str]:
    """Returns every environment variable name that maps to a setting.

    Returns:
        Names such as ``DOCINTEL_CHUNKING__CHUNK_SIZE``.
    """
    names: set[str] = set()
    for name, field in Settings.model_fields.items():
        group = field.annotation
        if isinstance(group, type) and issubclass(group, BaseModel):
            names.update(
                f"DOCINTEL_{name}__{sub}".upper() for sub in group.model_fields
            )
        else:
            names.add(f"DOCINTEL_{name}".upper())
    return names


def test_nested_variables_override_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCINTEL_CLOUD_ENV", "aws")
    monkeypatch.setenv("DOCINTEL_CHUNKING__CHUNK_SIZE", "500")
    monkeypatch.setenv("DOCINTEL_MATCHER__THRESHOLD", "0.85")

    settings = Settings(_env_file=None)

    assert settings.cloud_env == "aws"
    assert settings.chunking.chunk_size == 500
    assert settings.matcher.threshold == 0.85


def test_overlap_not_smaller_than_chunk_size_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCINTEL_CHUNKING__CHUNK_SIZE", "100")
    monkeypatch.setenv("DOCINTEL_CHUNKING__CHUNK_OVERLAP", "100")

    with pytest.raises(ValidationError, match="chunk_overlap"):
        Settings(_env_file=None)


def test_secrets_never_appear_in_settings_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "s3cr3t-sentinel"
    for name in (
        "DOCINTEL_QDRANT__API_KEY",
        "DOCINTEL_LLM__OPENAI_API_KEY",
        "DOCINTEL_LLM_OBSERVABILITY__LANGFUSE_SECRET_KEY",
        "DOCINTEL_BLOB__SECRET_ACCESS_KEY",
        "DOCINTEL_JOBS__POSTGRES_DSN",
    ):
        monkeypatch.setenv(name, secret)
    monkeypatch.setenv(
        "DOCINTEL_QUEUE__RABBITMQ_URL", f"amqp://user:{secret}@mq:5672/"
    )

    settings = Settings(_env_file=None)

    assert secret not in repr(settings)
    assert secret not in settings.model_dump_json()


def test_env_example_lists_only_real_settings_with_valid_values() -> None:
    lines = ENV_EXAMPLE.read_text().splitlines()
    keys = {
        line.split("=", 1)[0]
        for line in lines
        if line.strip() and not line.startswith("#")
    }

    assert keys <= _setting_env_names(), keys - _setting_env_names()
    Settings(_env_file=ENV_EXAMPLE)
