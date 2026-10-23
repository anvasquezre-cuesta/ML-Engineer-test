import pytest
from pydantic import ValidationError

from app.core.config import RAGSettings, Settings, get_settings


def test_defaults_are_the_documented_values() -> None:
    settings = Settings(_env_file=None)

    assert settings.ocr.dpi == 300
    assert settings.ner.model == "en_core_web_lg"
    assert settings.matching.threshold == 0.90
    assert (settings.rag.chunk_words, settings.rag.overlap_words) == (150, 30)


def test_nested_env_var_overrides_ocr_dpi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR__DPI", "200")

    assert get_settings().ocr.dpi == 200


def test_nested_env_var_overrides_llm_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM__BASE_URL", "http://llm.internal:8000/v1")

    assert get_settings().llm.base_url == "http://llm.internal:8000/v1"


def test_out_of_range_dpi_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR__DPI", "10")

    with pytest.raises(ValidationError):
        get_settings()


def test_overlap_must_be_smaller_than_chunk() -> None:
    with pytest.raises(ValidationError, match="overlap_words"):
        RAGSettings(chunk_words=50, overlap_words=50)


def test_api_key_is_not_leaked_in_repr() -> None:
    settings = Settings(_env_file=None)

    assert "ollama" not in repr(settings.llm)
