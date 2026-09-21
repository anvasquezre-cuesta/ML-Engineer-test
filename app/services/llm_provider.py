"""
Module: app.services.llm_provider
Path: app/services/llm_provider.py
Description: Configurable LLM provider boundary for grounded RAG generation.
"""

from typing import Protocol

import httpx
from langchain_ollama import ChatOllama

from app.config import Settings


class LLMProviderError(RuntimeError):
    """Raised when an LLM generation request cannot be completed."""


class LLMProvider(Protocol):
    """Define the application-level contract for LLM generation."""

    def generate(self, prompt: str) -> str:
        """Generate a response from the supplied prompt."""


class OllamaLLMProvider:
    """Generate responses using a configured local Ollama model."""

    def __init__(self, settings: Settings) -> None:
        self._max_attempts = settings.llm_max_retries + 1
        self._llm = ChatOllama(
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            temperature=settings.llm_temperature,
            sync_client_kwargs={"timeout": settings.llm_timeout},
        )

    def generate(self, prompt: str) -> str:
        """Generate a response, retrying external failures."""
        last_exception: Exception | None = None

        for _ in range(self._max_attempts):
            try:
                response = self._llm.invoke(prompt)
                return str(response.content)
            except Exception as exc:  # noqa: BLE001
                last_exception = exc

        raise LLMProviderError(
            "Failed to generate a response from the configured LLM."
        ) from last_exception


class OpenAICompatibleLLMProvider:
    """Generate responses through an OpenAI-compatible chat API."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.llm_base_url.rstrip("/")
        self._model = settings.llm_model
        self._api_key = settings.llm_api_key
        self._temperature = settings.llm_temperature
        self._timeout = settings.llm_timeout
        self._max_attempts = settings.llm_max_retries + 1

    def generate(self, prompt: str) -> str:
        """Generate a response, retrying transient HTTP failures."""

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": self._temperature,
        }

        headers = {
            "Content-Type": "application/json",
        }

        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        last_exception: Exception | None = None

        for _ in range(self._max_attempts):
            try:
                response = httpx.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self._timeout,
                )
                response.raise_for_status()

                response_data = response.json()
                content = response_data["choices"][0]["message"]["content"]

                if not isinstance(content, str) or not content.strip():
                    raise ValueError("The LLM returned an empty response.")

                return content

            except (
                httpx.HTTPError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
            ) as exc:
                last_exception = exc

        raise LLMProviderError(
            "Failed to generate a response from the configured OpenAI-compatible LLM."
        ) from last_exception
