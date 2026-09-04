import logging

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.errors import LLMError

log = logging.getLogger(__name__)


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and (
        exc.response.status_code == 429 or exc.response.status_code >= 500
    )


class OpenAICompatibleLLM:
    """Talks to any /chat/completions endpoint (OpenAI, Ollama, vLLM, OpenRouter...)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float,
        max_attempts: int,
        extra_body: dict | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.max_attempts = max_attempts
        self.extra_body = extra_body or {}
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    async def complete(self, system: str, user: str) -> str:
        if not self.api_key:
            raise LLMError("LLM_API_KEY is not configured")
        try:
            return await self._call(system, user)
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"LLM returned {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM unreachable: {exc.__class__.__name__}") from exc
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError("LLM returned an unexpected payload") from exc

    async def _call(self, system: str, user: str) -> str:
        # tenacity is applied here so the attempt count can come from config
        @retry(
            retry=retry_if_exception(_is_transient),
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=0.5, max=8),
            before_sleep=before_sleep_log(log, logging.WARNING),
            reraise=True,
        )
        async def attempt() -> str:
            body = {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                **self.extra_body,
            }
            response = await self.client.post("/chat/completions", json=body)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()

        return await attempt()

    async def aclose(self) -> None:
        await self.client.aclose()
