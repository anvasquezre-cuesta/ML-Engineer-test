"""LLM adapter: explicit credentials, provider errors as domain errors."""

import asyncio
from typing import Any

import botocore.exceptions
import httpx2
import langchain_aws
from langchain_core import messages
from langchain_core import outputs
from langchain_core.language_models import chat_models as lc_chat_models
from langchain_core.language_models import fake_chat_models
import openai
import pydantic
import pytest

from app import config
from app.adapters.langchain_llm import chat_models
from app.adapters.langchain_llm import llm
from app.adapters.noop_observability import observability as noop
from app.domain import errors
from app.domain import rag
from tests.fakes import llm_observability

PROMPT = rag.LlmPrompt(system="Use only the passages.", user="Who leads?")
REQUEST = httpx2.Request("POST", "https://llm.example/v1/chat/completions")


def status(code: int) -> httpx2.Response:
    """Builds an HTTP response with ``code`` for OpenAI errors.

    Args:
        code: The HTTP status.

    Returns:
        The response.
    """
    return httpx2.Response(code, request=REQUEST)


def aws_error(code: str) -> botocore.exceptions.ClientError:
    """Builds a Bedrock client error with ``code``.

    Args:
        code: The AWS error code.

    Returns:
        The error.
    """
    return botocore.exceptions.ClientError(
        {"Error": {"Code": code, "Message": "m"}}, "Converse"
    )


class FailingChat(lc_chat_models.BaseChatModel):
    """Chat model that raises ``error``, optionally after a delay."""

    error: Any = None
    delay_s: float = 0.0

    @property
    def _llm_type(self) -> str:
        """Names the fake.

        Returns:
            ``failing``.
        """
        return "failing"

    def _generate(self, *args: Any, **kwargs: Any) -> outputs.ChatResult:
        """Raises the configured error.

        Args:
            *args: Ignored.
            **kwargs: Ignored.

        Raises:
            Exception: Always, the configured error.
        """
        raise self.error

    async def _agenerate(self, *args: Any, **kwargs: Any) -> outputs.ChatResult:
        """Waits ``delay_s`` and raises the configured error.

        Args:
            *args: Ignored.
            **kwargs: Ignored.

        Raises:
            Exception: Always, the configured error.
        """
        await asyncio.sleep(self.delay_s)
        raise self.error


TIMEOUT = errors.LlmTimeoutError
UNAVAILABLE = errors.LlmUnavailableError
NOT_CONFIGURED = errors.LlmNotConfiguredError
BOTO = botocore.exceptions


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (openai.APITimeoutError(request=REQUEST), TIMEOUT),
        (BOTO.ReadTimeoutError(endpoint_url="b"), TIMEOUT),
        (openai.APIConnectionError(request=REQUEST), UNAVAILABLE),
        (
            openai.RateLimitError("r", response=status(429), body=None),
            UNAVAILABLE,
        ),
        (BOTO.EndpointConnectionError(endpoint_url="b"), UNAVAILABLE),
        (aws_error("ThrottlingException"), UNAVAILABLE),
        (aws_error("ResourceNotFoundException"), UNAVAILABLE),
        (
            openai.AuthenticationError("a", response=status(401), body=None),
            NOT_CONFIGURED,
        ),
        (aws_error("AccessDeniedException"), NOT_CONFIGURED),
        (aws_error("ValidationException"), BOTO.ClientError),
        (ValueError("bug"), ValueError),
    ],
)
async def test_provider_failures_become_domain_errors(
    error: Exception, expected: type[Exception]
) -> None:
    adapter = llm.LangChainLlm(
        FailingChat(error=error), noop.NoopObservability(), deadline_s=5
    )

    with pytest.raises(expected):
        await adapter.complete(PROMPT)


async def test_call_past_the_deadline_is_a_timeout() -> None:
    slow = FailingChat(error=RuntimeError("late"), delay_s=1.0)
    adapter = llm.LangChainLlm(slow, noop.NoopObservability(), deadline_s=0.01)

    with pytest.raises(errors.LlmTimeoutError):
        await adapter.complete(PROMPT)


async def test_answer_text_drops_reasoning_and_every_call_is_traced() -> None:
    reply = messages.AIMessage(
        content=[
            {"type": "reasoning_content", "reasoning_content": {"text": "x"}},
            {"type": "text", "text": "Robert Chen [1]."},
        ]
    )
    chat = fake_chat_models.GenericFakeChatModel(messages=iter([reply]))
    tracing = llm_observability.RecordingObservability()

    answer = await llm.LangChainLlm(chat, tracing, deadline_s=5).complete(
        PROMPT
    )

    assert answer == "Robert Chen [1]."
    [[sent]] = tracing.handler.calls
    assert [(m.type, m.content) for m in sent] == [
        ("system", PROMPT.system),
        ("human", PROMPT.user),
    ]


def test_bedrock_client_uses_only_the_configured_credentials() -> None:
    settings = config.LlmSettings(
        provider="bedrock",
        aws_access_key_id=pydantic.SecretStr("AKIA-TEST"),
        aws_secret_access_key=pydantic.SecretStr("secret"),
        max_retries=2,
        timeout_s=7,
    )

    chat = chat_models.build_chat_model(settings)

    assert isinstance(chat, langchain_aws.ChatBedrockConverse)
    key = chat.aws_access_key_id
    assert key is not None and key.get_secret_value() == "AKIA-TEST"
    assert chat.config.retries == {"total_max_attempts": 3, "mode": "standard"}
    assert chat.config.read_timeout == 7


def test_openai_without_a_key_is_not_configured() -> None:
    settings = config.LlmSettings(provider="openai", openai_api_key=None)

    with pytest.raises(errors.LlmNotConfiguredError):
        chat_models.build_chat_model(settings)
