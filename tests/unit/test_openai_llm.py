"""The OpenAI-compatible adapter against a mocked HTTP transport (no network)."""

import json

import httpx2  # openai >= 3 is built on httpx2, not httpx
import pytest
from pydantic import SecretStr

from app.adapters.openai_llm import OpenAICompatibleLLM
from app.core.config import LLMSettings
from app.domain.errors import UpstreamUnavailable

SETTINGS = LLMSettings(
    base_url="http://llm.test/v1",
    api_key=SecretStr("test-key"),
    model="tiny-model",
    timeout_s=2,
    max_retries=0,
    temperature=0,
)


def _completion(content: str | None) -> dict[str, object]:
    return {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "tiny-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def _llm(handler: httpx2.MockTransport, settings: LLMSettings = SETTINGS) -> OpenAICompatibleLLM:
    return OpenAICompatibleLLM(settings, http_client=httpx2.Client(transport=handler))


def test_sends_configured_model_messages_and_key() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=_completion("  Robert Chen.  "))

    answer = _llm(httpx2.MockTransport(handler)).complete("system rules", "question")

    (request,) = seen
    body = json.loads(request.content)
    assert str(request.url) == "http://llm.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    assert body["model"] == "tiny-model"
    assert body["temperature"] == 0
    assert body["messages"] == [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "question"},
    ]
    assert answer == "Robert Chen."


def test_connection_error_becomes_upstream_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    with pytest.raises(UpstreamUnavailable, match="unavailable"):
        _llm(httpx2.MockTransport(handler)).complete("s", "u")


def test_timeout_becomes_upstream_unavailable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out")

    with pytest.raises(UpstreamUnavailable):
        _llm(httpx2.MockTransport(handler)).complete("s", "u")


def test_server_errors_are_retried_then_reported() -> None:
    attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        return httpx2.Response(503, json={"error": {"message": "overloaded"}})

    settings = SETTINGS.model_copy(update={"max_retries": 2})
    with pytest.raises(UpstreamUnavailable):
        _llm(httpx2.MockTransport(handler), settings).complete("s", "u")

    assert attempts == 3  # the first try plus two retries


def test_a_transient_failure_is_recovered_by_retry() -> None:
    responses = iter([httpx2.Response(500), httpx2.Response(200, json=_completion("ok"))])

    settings = SETTINGS.model_copy(update={"max_retries": 1})
    answer = _llm(httpx2.MockTransport(lambda request: next(responses)), settings).complete(
        "s", "u"
    )

    assert answer == "ok"


def test_unknown_model_is_reported_not_raised_raw() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, json={"error": {"message": "model 'tiny-model' not found"}})

    with pytest.raises(UpstreamUnavailable, match="not found"):
        _llm(httpx2.MockTransport(handler)).complete("s", "u")


def test_empty_content_is_an_empty_answer() -> None:
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, json=_completion(None)))

    assert _llm(transport).complete("s", "u") == ""


def _models(*ids: str) -> dict[str, object]:
    return {
        "object": "list",
        "data": [{"id": i, "object": "model", "created": 0, "owned_by": "x"} for i in ids],
    }


def test_ping_succeeds_when_the_configured_model_is_served() -> None:
    transport = httpx2.MockTransport(
        lambda request: httpx2.Response(200, json=_models("other", "tiny-model"))
    )

    assert _llm(transport).ping() == "tiny-model available"


def test_ping_fails_when_the_model_is_not_pulled() -> None:
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, json=_models("other")))

    with pytest.raises(UpstreamUnavailable, match="not served"):
        _llm(transport).ping()


def test_ping_fails_fast_when_the_endpoint_is_down() -> None:
    attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        raise httpx2.ConnectError("connection refused")

    settings = SETTINGS.model_copy(update={"max_retries": 5})
    with pytest.raises(UpstreamUnavailable):
        _llm(httpx2.MockTransport(handler), settings).ping()

    assert attempts == 1  # readiness never waits for the request retries
