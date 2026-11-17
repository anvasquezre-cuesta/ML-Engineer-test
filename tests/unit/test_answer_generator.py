"""Provider protocol tests use in-memory HTTP responses, never a real API."""

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.answer_generator import GeneratorRateLimitError, GeneratorTimeoutError, HTTPAnswerGenerator, MAX_PROVIDER_BYTES
from app.services.ask_service import AnswerGenerationError, ContextFragment


def settings(provider):
    return Settings(llm_provider=provider, llm_model="test-model", llm_api_key="test-key",
                    llm_allow_external=True)


def test_prompt_covers_partial_answers_and_plan_versus_actual():
    # This verifies the instruction, not that a real model will obey it.
    from app.services.answer_generator import SYSTEM
    assert "each supported part" in SYSTEM
    assert "scheduled event as completed" in SYSTEM
    assert "approved budget as actual spending" in SYSTEM


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_provider_protocol_and_secret_handling(provider):
    async def run():
        seen = []
        def handler(request):
            seen.append(request)
            body = json.loads(request.content)
            encoded = json.dumps(body)
            assert "private question" in encoded and "untrusted context" in encoded
            if provider == "openai":
                assert request.headers["authorization"] == "Bearer test-key"
                assert request.url.host == "api.openai.com"
                data = {"choices": [{"message": {"content": '{"answer":"ok","citations":[{"id":"S1","quote":"untrusted context"}]}'}}]}
            else:
                assert request.headers["x-goog-api-key"] == "test-key"
                assert request.url.host == "generativelanguage.googleapis.com"
                data = {"candidates": [{"content": {"parts": [{"text": '{"answer":"ok","citations":[{"id":"S1","quote":"untrusted context"}]}'}]}}]}
            assert "test-key" not in str(request.url) and "test-key" not in encoded
            return httpx.Response(200, json=data)
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
        generator = HTTPAnswerGenerator(settings(provider), client=client)
        result = await generator.generate("private question", (ContextFragment("S1", "untrusted context"),))
        assert result.answer == "ok" and result.citations[0].citation_id == "S1"
        assert result.citations[0].quote == "untrusted context" and len(seen) == 1
        await generator.aclose()
        assert client.is_closed
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_external_models_require_explicit_permission_and_key(provider):
    with pytest.raises(ValidationError):
        Settings(llm_provider=provider, llm_model="model", llm_api_key="key")
    with pytest.raises(ValidationError):
        Settings(llm_provider=provider, llm_model="model", llm_allow_external=True)


def test_disabled_needs_no_model_or_key_and_secrets_are_hidden():
    assert Settings().llm_provider == "disabled"
    assert "test-key" not in repr(settings("openai"))
    with pytest.raises(ValidationError) as error:
        Settings(llm_provider="openai", llm_model="model", llm_api_key="secret-key")
    assert "secret-key" not in str(error.value)


def test_local_generation_is_not_a_supported_provider():
    with pytest.raises(ValidationError):
        Settings(llm_provider="local", llm_model="model")


@pytest.mark.parametrize("url", [
    "http://example.com/v1", "https://user:password@example.com/v1", "https://example.com/v1?key=secret",
    "https://example.com/v1#fragment", "https://example.com:bad/v1", "https://example.com:0/v1",
    "https://example.com/\nheader", "https://example.com\\@evil.com/v1", "https://%65xample.com/v1",
])
def test_openai_base_url_rejects_unsafe_destinations_without_echoing_credentials(url):
    with pytest.raises(ValidationError) as error:
        Settings(llm_provider="openai", llm_model="test", llm_api_key="private-api-key",
                 llm_allow_external=True, llm_openai_base_url=url)
    assert "private-api-key" not in str(error.value) and "password" not in str(error.value)


def test_openai_compatible_base_url_uses_configured_path_and_secret_header():
    async def run():
        def handler(request):
            assert str(request.url) == "https://trusted.example/custom/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer test-key"
            return httpx.Response(200, json={"choices": [{"message": {
                "content": '{"answer":"ok","citations":[{"id":"S1","quote":"context"}]}'
            }}]})
        config = Settings(llm_provider="openai", llm_model="test-model", llm_api_key="test-key",
                          llm_allow_external=True, llm_openai_base_url="https://trusted.example/custom/v1/")
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
        generator = HTTPAnswerGenerator(config, client=client)
        try:
            result = await generator.generate("question", (ContextFragment("S1", "context"),))
            assert result.answer == "ok"
        finally:
            await generator.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_transient_http_errors_retry_once_then_succeed(status):
    async def run():
        calls = []
        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(status)
            return httpx.Response(200, json={"choices": [{"message": {
                "content": '{"answer":"ok","citations":[{"id":"S1","quote":"context"}]}'
            }}]})
        config = settings("openai").model_copy(update={"llm_retry_backoff_seconds": 0})
        generator = HTTPAnswerGenerator(config, client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False,
        ))
        try:
            assert (await generator.generate("question", (ContextFragment("S1", "context"),))).answer == "ok"
            assert len(calls) == 2
        finally:
            await generator.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ConnectTimeout])
def test_connect_failures_are_retried_with_a_bounded_attempt_count(error_type):
    async def run():
        calls = []
        def handler(request):
            calls.append(1)
            raise error_type("private connection detail", request=request)
        config = settings("openai").model_copy(update={"llm_max_retries": 2, "llm_retry_backoff_seconds": 0})
        generator = HTTPAnswerGenerator(config, client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False,
        ))
        try:
            with pytest.raises(GeneratorTimeoutError if error_type is httpx.ConnectTimeout else AnswerGenerationError):
                await generator.generate("question", (ContextFragment("S1", "context"),))
            assert len(calls) == 3
        finally:
            await generator.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("status", [400, 401, 403, 429])
def test_client_errors_are_not_retried(status):
    async def run():
        calls = []
        def handler(request):
            calls.append(1)
            return httpx.Response(status)
        config = settings("openai").model_copy(update={"llm_retry_backoff_seconds": 0})
        generator = HTTPAnswerGenerator(config, client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False,
        ))
        try:
            with pytest.raises(GeneratorRateLimitError if status == 429 else AnswerGenerationError):
                await generator.generate("question", (ContextFragment("S1", "context"),))
            assert calls == [1]
        finally:
            await generator.aclose()
    asyncio.run(run())


def test_disabling_retries_and_cancellation_during_backoff():
    async def run():
        calls, started = [], asyncio.Event()
        def handler(request):
            calls.append(1)
            started.set()
            return httpx.Response(503)
        config = settings("openai").model_copy(update={"llm_max_retries": 0})
        generator = HTTPAnswerGenerator(config, client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False,
        ))
        try:
            with pytest.raises(AnswerGenerationError):
                await generator.generate("question", (ContextFragment("S1", "context"),))
            assert len(calls) == 1
        finally:
            await generator.aclose()

        calls.clear()
        started.clear()
        config = settings("openai").model_copy(update={"llm_retry_backoff_seconds": 5})
        generator = HTTPAnswerGenerator(config, client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False,
        ))
        try:
            task = asyncio.create_task(generator.generate("question", (ContextFragment("S1", "context"),)))
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert len(calls) == 1
        finally:
            await generator.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("response", [
    httpx.Response(500, text="sensitive provider response"),
    httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok","citations":"S1"}'}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok","citations":["S1"]}'}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok","citations":[{"id":"S1"}]}'}}]}),
    httpx.Response(200, content=b"x" * (MAX_PROVIDER_BYTES + 1)),
])
def test_bad_provider_response_fails_without_disclosing_content(response):
    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response), trust_env=False)
        generator = HTTPAnswerGenerator(settings("openai"), client=client)
        try:
            with pytest.raises(AnswerGenerationError) as error:
                await generator.generate("question", (ContextFragment("S1", "context"),))
            assert "sensitive provider response" not in str(error.value)
        finally:
            await generator.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("timeout_type", [httpx.ReadTimeout, httpx.WriteTimeout])
def test_provider_timeout_is_distinct_and_not_retried(timeout_type):
    calls = []
    def timeout(request):
        calls.append(1)
        raise timeout_type("sensitive details", request=request)
    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(timeout), trust_env=False)
        generator = HTTPAnswerGenerator(settings("openai"), client=client)
        try:
            with pytest.raises(GeneratorTimeoutError, match="^Model provider timed out$"):
                await generator.generate("question", (ContextFragment("S1", "context"),))
        finally:
            await generator.aclose()
        assert len(calls) == 1
    asyncio.run(run())


def test_provider_rate_limit_is_distinct_and_not_retried():
    calls = []
    def limited(request):
        calls.append(1)
        return httpx.Response(429, text="private provider detail")
    async def run():
        generator = HTTPAnswerGenerator(settings("openai"), client=httpx.AsyncClient(
            transport=httpx.MockTransport(limited), trust_env=False,
        ))
        try:
            with pytest.raises(GeneratorRateLimitError, match="^Model provider rate or quota limit$"):
                await generator.generate("question", (ContextFragment("S1", "context"),))
        finally:
            await generator.aclose()
        assert calls == [1]
    asyncio.run(run())


def test_gemini_ignores_thought_parts_and_uses_visible_answer():
    async def run():
        response = httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"thought": True, "text": "private thought, not JSON"},
            {"text": '{"answer":"ok","citations":[{"id":"S1","quote":"context"}]}'},
        ]}}]})
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response), trust_env=False)
        generator = HTTPAnswerGenerator(settings("gemini"), client=client)
        try:
            result = await generator.generate("question", (ContextFragment("S1", "context"),))
            assert result.answer == "ok" and result.citations[0].quote == "context"
        finally:
            await generator.aclose()
    asyncio.run(run())


def test_gemini_missing_content_logs_only_safe_finish_reason(caplog):
    async def run():
        response = httpx.Response(200, json={"candidates": [{"finishReason": "MAX_TOKENS"}]})
        generator = HTTPAnswerGenerator(settings("gemini"), client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: response), trust_env=False,
        ))
        try:
            with pytest.raises(AnswerGenerationError):
                await generator.generate("sensitive question", (ContextFragment("S1", "private content"),))
        finally:
            await generator.aclose()
    asyncio.run(run())
    assert "reason=MAX_TOKENS" in caplog.text and "stage=provider_content" in caplog.text
    assert "sensitive question" not in caplog.text and "private content" not in caplog.text


def test_gemini_truncated_completion_is_rejected_even_if_json_is_valid():
    async def run():
        response = httpx.Response(200, json={"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [
            {"text": '{"answer":"ok","citations":[{"id":"S1","quote":"context"}]}'},
        ]}}]})
        generator = HTTPAnswerGenerator(settings("gemini"), client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: response), trust_env=False,
        ))
        try:
            with pytest.raises(AnswerGenerationError):
                await generator.generate("question", (ContextFragment("S1", "context"),))
        finally:
            await generator.aclose()
    asyncio.run(run())
