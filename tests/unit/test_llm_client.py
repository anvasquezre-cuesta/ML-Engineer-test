import json
import time

import httpx
import pytest

from app.config import get_settings
from app.services.llm_client import (
    LLMBadResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    chat,
)

MESSAGES = [{"role": "user", "content": "hi"}]
OK = httpx.Response(200, json={"choices": [{"message": {"content": " ok "}}]})


@pytest.fixture
def llm_env(monkeypatch):
    """Pin every LLM_* setting so a local .env cannot leak in; no waiting."""
    for key, value in {
        "LLM_BASE_URL": "http://llm.test/v1",
        "LLM_MODEL": "m",
        "LLM_API_KEY": "",
        "LLM_MAX_TOKENS": "7",
        "LLM_TIMEOUT_S": "7",
        "LLM_CONNECT_TIMEOUT_S": "3",
        "LLM_MAX_ATTEMPTS": "3",
        "LLM_RETRY_MAX_WAIT_S": "0",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def replay(*steps):
    """MockTransport that plays one step per request; returns it and the requests seen.

    A step is a status code, a ready httpx.Response or an exception class to raise.
    """
    requests = []

    def handler(request):
        requests.append(request)
        step = steps[len(requests) - 1]
        if isinstance(step, type):
            raise step("boom", request=request)
        return step if isinstance(step, httpx.Response) else httpx.Response(step)

    return httpx.MockTransport(handler), requests


def test_ac_llm_01_retries_5xx_and_sends_config(llm_env, monkeypatch):
    transport, requests = replay(503, 503, OK)
    assert chat(MESSAGES, transport) == "ok"
    assert len(requests) == 3
    assert str(requests[0].url) == "http://llm.test/v1/chat/completions"
    body = json.loads(requests[0].content)
    assert body["model"] == "m"
    assert body["temperature"] == 0
    assert body["max_tokens"] == 7
    assert body["messages"] == MESSAGES
    assert "authorization" not in requests[0].headers
    assert requests[0].extensions["timeout"] == {
        "connect": 3.0,
        "read": 7.0,
        "write": 7.0,
        "pool": 7.0,
    }

    monkeypatch.setenv("LLM_API_KEY", "k")
    get_settings.cache_clear()
    transport, requests = replay(OK)
    chat(MESSAGES, transport)
    assert requests[0].headers["authorization"] == "Bearer k"


def test_ac_llm_02_429_is_retried(llm_env):
    transport, requests = replay(429, OK)
    assert chat(MESSAGES, transport) == "ok"
    assert len(requests) == 2


@pytest.mark.parametrize(
    "reply",
    [
        400,
        httpx.Response(200, json={}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
        httpx.Response(200, content=b"<html>not json</html>"),
    ],
    ids=["400", "no-choices", "null-content", "not-json"],
)
def test_ac_llm_02_bad_reply_is_bad_response(llm_env, reply):
    transport, requests = replay(reply)
    with pytest.raises(LLMBadResponseError):
        chat(MESSAGES, transport)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "step", [503, httpx.ConnectError], ids=["503", "connect-error"]
)
def test_ac_llm_03_unreachable_after_max_attempts(llm_env, monkeypatch, step):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "4")  # not the default, so 3 is not fixed
    get_settings.cache_clear()
    transport, requests = replay(*[step] * 4)
    start = time.perf_counter()
    with pytest.raises(LLMUnavailableError):
        chat(MESSAGES, transport)
    assert len(requests) == 4
    assert time.perf_counter() - start < 0.1


def test_ac_llm_03_timeout_after_max_attempts(llm_env, monkeypatch):
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "4")
    get_settings.cache_clear()
    transport, requests = replay(*[httpx.ReadTimeout] * 4)
    with pytest.raises(LLMTimeoutError):
        chat(MESSAGES, transport)
    assert len(requests) == 4
