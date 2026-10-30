"""Client for an OpenAI-compatible chat endpoint, with timeout and retries."""

from typing import Protocol

import httpx
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import get_settings


class LLMUnavailableError(RuntimeError):
    """The LLM is unreachable, or kept answering 429/5xx."""


class LLMTimeoutError(RuntimeError):
    """The LLM did not answer in time on every attempt."""


class LLMBadResponseError(RuntimeError):
    """The LLM rejected the request or its reply has no text."""


class LLM(Protocol):
    def __call__(self, messages: list[dict]) -> str: ...


def _transient(err: BaseException) -> bool:
    """True for errors worth retrying: network failures, 429 and 5xx."""
    if isinstance(err, httpx.HTTPStatusError):
        return err.response.status_code == 429 or err.response.status_code >= 500
    return isinstance(err, httpx.TransportError)


def chat(messages: list[dict], transport: httpx.BaseTransport | None = None) -> str:
    """Send the messages and return the reply text; `transport` is for tests."""
    settings = get_settings()
    headers = (
        {"Authorization": f"Bearer {settings.llm_api_key}"}
        if settings.llm_api_key
        else {}
    )
    body = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": settings.llm_max_tokens,
    }
    retrying = Retrying(
        retry=retry_if_exception(_transient),
        stop=stop_after_attempt(settings.llm_max_attempts),
        wait=wait_exponential_jitter(multiplier=0.5, max=settings.llm_retry_max_wait_s),
        reraise=True,
    )
    timeout = httpx.Timeout(
        settings.llm_timeout_s, connect=settings.llm_connect_timeout_s
    )
    try:
        with httpx.Client(
            base_url=settings.llm_base_url, timeout=timeout, transport=transport
        ) as client:
            for attempt in retrying:
                with attempt:
                    response = client.post(
                        "/chat/completions", json=body, headers=headers
                    )
                    response.raise_for_status()
    except httpx.TimeoutException as err:  # before TransportError: it is a subclass
        raise LLMTimeoutError("the LLM timed out") from err
    except httpx.TransportError as err:
        raise LLMUnavailableError("the LLM is unreachable") from err
    except httpx.HTTPStatusError as err:
        status = err.response.status_code
        if _transient(err):
            raise LLMUnavailableError(f"the LLM answered {status}") from err
        raise LLMBadResponseError(f"the LLM rejected the request: {status}") from err
    try:
        return response.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as err:
        raise LLMBadResponseError("the LLM reply has no text") from err
