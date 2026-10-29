import json
from collections.abc import Callable

import httpx2  # the HTTP client the openai SDK is built on
import pytest

from app.domain.errors import LlmNotConfigured, LlmRateLimited, LlmTimeout, LlmUnavailable
from app.domain.grounding import LlmReply, Prompt
from app.infrastructure.openai_answer_generator import OpenAiCompatibleAnswerGenerator

PROMPT = Prompt(system="rules", user='<passage n="1">\ntext\n</passage>\n\nQuestion: q')
SECRET_KEY = "gsk_test_secret_value"  # noqa: S105 — fake key; tests prove it never leaks


def _generator(
    handler: Callable[[httpx2.Request], httpx2.Response], api_key: str | None = SECRET_KEY
) -> OpenAiCompatibleAnswerGenerator:
    return OpenAiCompatibleAnswerGenerator(
        base_url="https://llm.example/v1",
        api_key=api_key,
        model="llama-3.3-70b-versatile",
        timeout_seconds=5.0,
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )


def _completion(content: str, usage: dict[str, int] | None) -> httpx2.Response:
    body: dict[str, object] = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "llama-3.3-70b-versatile",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    if usage is not None:
        body["usage"] = {**usage, "total_tokens": sum(usage.values())}
    return httpx2.Response(200, json=body)


def test_reply_text_model_and_usage_are_returned() -> None:
    sent: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return _completion("Robert Chen [1].", {"prompt_tokens": 812, "completion_tokens": 14})

    reply = _generator(handler).generate(PROMPT)

    assert reply == LlmReply("Robert Chen [1].", "llama-3.3-70b-versatile", 812, 14)
    assert sent[0]["temperature"] == 0
    assert sent[0]["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": PROMPT.user},
    ]


def test_missing_usage_counts_as_zero() -> None:
    reply = _generator(lambda request: _completion("ok [1].", None)).generate(PROMPT)

    assert (reply.prompt_tokens, reply.completion_tokens) == (0, 0)


def test_no_api_key_means_not_configured_and_no_request() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return _completion("never", None)

    with pytest.raises(LlmNotConfigured):
        _generator(handler, api_key=None).generate(PROMPT)
    assert requests == []


def _raise_timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("timed out", request=request)


@pytest.mark.parametrize(
    ("handler", "error"),
    [
        (_raise_timeout, LlmTimeout),
        (
            lambda request: httpx2.Response(429, json={"error": {"message": "slow down"}}),
            LlmRateLimited,
        ),
        (lambda request: httpx2.Response(500, json={"error": {"message": "boom"}}), LlmUnavailable),
        (
            lambda request: httpx2.Response(401, json={"error": {"message": "bad key"}}),
            LlmUnavailable,
        ),
    ],
)
def test_provider_errors_are_translated_without_leaking_the_key(
    handler: Callable[[httpx2.Request], httpx2.Response], error: type[Exception]
) -> None:
    with pytest.raises(error) as raised:
        _generator(handler).generate(PROMPT)

    assert SECRET_KEY not in str(raised.value)
