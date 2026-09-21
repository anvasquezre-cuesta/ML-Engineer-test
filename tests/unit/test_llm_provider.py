"""
Module: tests.unit.test_llm_provider
Path: tests/unit/test_llm_provider.py
Description: Unit tests for configurable LLM provider implementations.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.config import Settings
from app.services.llm_provider import (
    LLMProviderError,
    OpenAICompatibleLLMProvider,
)


def create_settings(**overrides: object) -> Settings:
    """Create test settings with deterministic LLM configuration."""
    values = {
        "llm_provider": "openai_compatible",
        "llm_model": "test-model",
        "llm_base_url": "https://example.com/v1",
        "llm_api_key": "test-api-key",
        "llm_temperature": 0.0,
        "llm_timeout": 10.0,
        "llm_max_retries": 2,
    }
    values.update(overrides)
    return Settings(**values)


def test_openai_compatible_provider_returns_generated_content() -> None:
    """Return the assistant content from a successful API response."""
    settings = create_settings()
    provider = OpenAICompatibleLLMProvider(settings)

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "The answer is grounded in the document.",
                }
            }
        ]
    }

    with patch(
        "app.services.llm_provider.httpx.post",
        return_value=response,
    ) as mock_post:
        result = provider.generate("What is the answer?")

    assert result == "The answer is grounded in the document."

    mock_post.assert_called_once_with(
        "https://example.com/v1/chat/completions",
        json={
            "model": "test-model",
            "messages": [
                {
                    "role": "user",
                    "content": "What is the answer?",
                }
            ],
            "temperature": 0.0,
        },
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer test-api-key",
        },
        timeout=10.0,
    )


def test_openai_compatible_provider_works_without_api_key() -> None:
    """Allow compatible local endpoints that do not require authentication."""
    settings = create_settings(llm_api_key=None)
    provider = OpenAICompatibleLLMProvider(settings)

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "Local response.",
                }
            }
        ]
    }

    with patch(
        "app.services.llm_provider.httpx.post",
        return_value=response,
    ) as mock_post:
        result = provider.generate("Test prompt")

    assert result == "Local response."

    assert mock_post.call_args.kwargs["headers"] == {
        "Content-Type": "application/json",
    }


def test_openai_compatible_provider_retries_after_http_failure() -> None:
    """Retry failed external requests according to configured retry policy."""
    settings = create_settings(llm_max_retries=2)
    provider = OpenAICompatibleLLMProvider(settings)

    response = MagicMock()
    response.raise_for_status.side_effect = [
        httpx.HTTPStatusError(
            "server error",
            request=MagicMock(),
            response=MagicMock(),
        ),
        None,
    ]
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "Recovered response.",
                }
            }
        ]
    }

    with patch(
        "app.services.llm_provider.httpx.post",
        return_value=response,
    ) as mock_post:
        result = provider.generate("Retry test")

    assert result == "Recovered response."
    assert mock_post.call_count == 2


def test_openai_compatible_provider_raises_after_all_retries() -> None:
    """Raise the application-level error when all attempts fail."""
    settings = create_settings(llm_max_retries=2)
    provider = OpenAICompatibleLLMProvider(settings)

    with (
        patch(
            "app.services.llm_provider.httpx.post",
            side_effect=httpx.TimeoutException("request timed out"),
        ) as mock_post,
        pytest.raises(LLMProviderError),
    ):
        provider.generate("Timeout test")

    assert mock_post.call_count == 3


def test_openai_compatible_provider_rejects_empty_response() -> None:
    """Raise an application-level error when the model returns no content."""
    settings = create_settings(llm_max_retries=0)
    provider = OpenAICompatibleLLMProvider(settings)

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "   ",
                }
            }
        ]
    }

    with (
        patch(
            "app.services.llm_provider.httpx.post",
            return_value=response,
        ),
        pytest.raises(LLMProviderError),
    ):
        provider.generate("Empty response test")
