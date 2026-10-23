"""``LLMClient`` for any OpenAI-compatible chat endpoint (OpenAI, Ollama, vLLM, ...).

Host, key, model, timeout and retries all come from config. The OpenAI client
retries connection errors, timeouts, 408/409/429 and 5xx with exponential
backoff; once its retries are spent, every failure becomes
``UpstreamUnavailable`` (503) instead of a stack trace.
"""

from typing import TYPE_CHECKING

import openai

from app.core.config import LLMSettings
from app.domain.errors import UpstreamUnavailable

if TYPE_CHECKING:
    import httpx2  # openai >= 3 is built on httpx2, not httpx


class OpenAICompatibleLLM:
    def __init__(self, settings: LLMSettings, http_client: "httpx2.Client | None" = None) -> None:
        self._client = openai.OpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key.get_secret_value(),
            timeout=settings.timeout_s,
            max_retries=settings.max_retries,
            http_client=http_client,
        )
        self._model = settings.model
        self._readiness_timeout_s = settings.readiness_timeout_s
        self._temperature = settings.temperature

    def complete(self, system: str, user: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                temperature=self._temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except openai.APIError as exc:  # connection, timeout and HTTP status errors
            raise UpstreamUnavailable(f"The language model is unavailable: {exc}") from exc
        if not response.choices:
            raise UpstreamUnavailable("The language model returned no answer.")
        return (response.choices[0].message.content or "").strip()

    def ping(self) -> str:
        """Readiness probe: the endpoint answers and serves the configured model."""
        try:
            models = self._client.with_options(
                timeout=self._readiness_timeout_s, max_retries=0
            ).models.list()
        except openai.APIError as exc:
            raise UpstreamUnavailable(f"The language model is unavailable: {exc}") from exc
        available = {model.id for model in models}
        if self._model not in available:
            raise UpstreamUnavailable(f"Model '{self._model}' is not served by the endpoint.")
        return f"{self._model} available"
