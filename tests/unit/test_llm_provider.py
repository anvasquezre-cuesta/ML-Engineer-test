"""
Module: tests.unit.test_llm_provider
Path: tests/unit/test_llm_provider.py
Description: Unit tests for the configurable LLM provider.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.services.llm_provider import LLMProviderError, OllamaLLMProvider


def test_generate_returns_llm_response() -> None:
    settings = Settings(
        llm_model="test-model",
        llm_base_url="http://test-llm",
        llm_temperature=0.0,
        llm_timeout=10.0,
        llm_max_retries=0,
    )

    mock_response = MagicMock()
    mock_response.content = "Grounded answer."

    with patch("app.services.llm_provider.ChatOllama") as mock_chat_ollama:
        mock_llm = mock_chat_ollama.return_value
        mock_llm.invoke.return_value = mock_response

        provider = OllamaLLMProvider(settings)
        result = provider.generate("What is the document about?")

    assert result == "Grounded answer."
    mock_llm.invoke.assert_called_once_with("What is the document about?")


def test_generate_retries_and_raises_provider_error_after_failures() -> None:
    settings = Settings(
        llm_model="test-model",
        llm_base_url="http://test-llm",
        llm_temperature=0.0,
        llm_timeout=10.0,
        llm_max_retries=2,
    )

    with patch("app.services.llm_provider.ChatOllama") as mock_chat_ollama:
        mock_llm = mock_chat_ollama.return_value
        mock_llm.invoke.side_effect = RuntimeError("LLM unavailable")

        provider = OllamaLLMProvider(settings)

        with pytest.raises(LLMProviderError, match="Failed to generate"):
            provider.generate("What is the document about?")

    assert mock_llm.invoke.call_count == 3
