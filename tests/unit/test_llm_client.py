import json

import httpx
import pytest
import respx

from app.core.errors import LLMError
from app.services.llm_client import OpenAICompatibleLLM

BASE = "http://llm.test/v1"


def make_client(key="k", attempts=3, extra_body=None):
    return OpenAICompatibleLLM(BASE, key, "m", 1, attempts, extra_body)


def ok(content="hi"):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@respx.mock
async def test_retries_transient_failures_then_succeeds():
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(503), ok(" answer ")]
    )
    assert await make_client().complete("s", "u") == "answer"
    assert route.call_count == 3


@respx.mock
async def test_gives_up_after_max_attempts():
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(500))
    with pytest.raises(LLMError):
        await make_client(attempts=2).complete("s", "u")
    assert route.call_count == 2


@respx.mock
async def test_auth_errors_are_not_retried():
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(401))
    with pytest.raises(LLMError, match="401"):
        await make_client().complete("s", "u")
    assert route.call_count == 1


async def test_missing_key_fails_fast():
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        await make_client(key="").complete("s", "u")


@respx.mock
async def test_unexpected_payload():
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(LLMError, match="payload"):
        await make_client().complete("s", "u")


@respx.mock
async def test_extra_body_is_merged_into_the_request():
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=ok())
    extra = {"chat_template_kwargs": {"enable_thinking": False}}
    await make_client(extra_body=extra).complete("s", "u")
    sent = json.loads(route.calls.last.request.content)
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent["model"] == "m" and len(sent["messages"]) == 2
