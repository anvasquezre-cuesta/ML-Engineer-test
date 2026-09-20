"""
Module: app.services.llm_provider
Path: app/services/llm_provider.py
Description: Configurable LLM provider boundary for grounded RAG generation.
"""

from typing import Protocol

from langchain_ollama import ChatOllama

from app.config import Settings


class LLMProviderError(RuntimeError):
    """Raised when an LLM generation request cannot be completed."""


class LLMProvider(Protocol):
    """Define the application-level contract for LLM generation."""

    def generate(self, prompt: str) -> str:
        """Generate a response from the supplied prompt."""


class OllamaLLMProvider:
    """Generate responses using a configured Ollama-compatible LLM."""

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
                return response.content
            # External provider libraries may expose different exception types.
            # Catching here lets us retry and translate them into our domain error.
            except Exception as exc:  # noqa: BLE001
                last_exception = exc

        raise LLMProviderError(
            "Failed to generate a response from the configured LLM."
        ) from last_exception
