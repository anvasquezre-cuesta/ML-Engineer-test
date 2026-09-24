"""Llm backed by a LangChain chat model, with a deadline and error mapping."""

import asyncio

import botocore.exceptions
from langchain_core import messages
from langchain_core.language_models import chat_models
import openai

from app.domain import errors
from app.domain import rag
from app.ports import llm
from app.ports import llm_observability

_BEDROCK_UNAVAILABLE = frozenset(
    {
        "ThrottlingException",
        "ServiceUnavailableException",
        "InternalServerException",
        "ModelNotReadyException",
        # Seen transiently for valid cross-region inference profiles; a
        # mistyped model id also lands here.
        "ResourceNotFoundException",
    }
)
_BEDROCK_NOT_CONFIGURED = frozenset(
    {
        "AccessDeniedException",
        "UnrecognizedClientException",
        "ExpiredTokenException",
    }
)


class LangChainLlm(llm.Llm):
    """Sends the prompt as system and user messages and returns the text."""

    def __init__(
        self,
        chat: chat_models.BaseChatModel,
        observability: llm_observability.LlmObservability,
        deadline_s: float,
    ) -> None:
        """Initializes the adapter.

        Args:
            chat: The chat model, loaded once.
            observability: Supplies the tracing callbacks.
            deadline_s: Total time one call may take, SDK retries included.
        """
        self._chat = chat
        self._observability = observability
        self._deadline_s = deadline_s

    async def complete(self, prompt: rag.LlmPrompt) -> str:  # noqa: DOC503
        """Generates a completion for ``prompt``.

        Timeouts, including the overall deadline, become
        ``LlmTimeoutError``; connection failures, throttling and server
        errors that outlast the SDK's retries become ``LlmUnavailableError``;
        rejected credentials become ``LlmNotConfiguredError``. Anything else
        is raised unchanged.

        Args:
            prompt: System instructions and user message.

        Returns:
            The text of the completion, without reasoning blocks.

        Raises:
            errors.LlmTimeoutError: If the call or the deadline times out.
            errors.LlmUnavailableError: If the provider stays unavailable.
            errors.LlmNotConfiguredError: If the credentials are rejected.
        """
        sent = [
            messages.SystemMessage(prompt.system),
            messages.HumanMessage(prompt.user),
        ]
        try:
            async with asyncio.timeout(self._deadline_s):
                reply = await self._chat.ainvoke(
                    sent, config={"callbacks": self._observability.callbacks()}
                )
        except TimeoutError as exc:
            raise errors.LlmTimeoutError() from exc
        except Exception as exc:
            translated = _translate(exc)
            if translated is None:
                raise
            raise translated from exc
        return _text(reply.content)


def _translate(exc: Exception) -> errors.AppError | None:
    """Maps a provider SDK failure to a domain error.

    Args:
        exc: The failure raised by the chat model.

    Returns:
        The domain error, or ``None`` when the failure is not the
        provider's to report (e.g. an invalid request).
    """
    match exc:
        case (
            openai.APITimeoutError()
            | botocore.exceptions.ReadTimeoutError()
            | botocore.exceptions.ConnectTimeoutError()
        ):
            return errors.LlmTimeoutError()
        case (
            openai.APIConnectionError()
            | botocore.exceptions.EndpointConnectionError()
        ):
            return errors.LlmUnavailableError()
        case openai.APIStatusError(status_code=401 | 403):
            return errors.LlmNotConfiguredError()
        case openai.APIStatusError(status_code=code) if (
            code == 429 or code >= 500
        ):
            return errors.LlmUnavailableError()
        case botocore.exceptions.ClientError():
            aws_code = exc.response.get("Error", {}).get("Code", "")
            if aws_code in _BEDROCK_UNAVAILABLE:
                return errors.LlmUnavailableError()
            if aws_code in _BEDROCK_NOT_CONFIGURED:
                return errors.LlmNotConfiguredError()
            if aws_code == "ModelTimeoutException":
                return errors.LlmTimeoutError()
    return None


def _text(content: str | list[str | dict[str, object]]) -> str:
    """Joins the text parts of a reply, dropping reasoning blocks.

    Args:
        content: The reply content, plain or as content blocks.

    Returns:
        The answer text.
    """
    if isinstance(content, str):
        return content
    return "".join(
        part
        if isinstance(part, str)
        else str(part["text"])
        if part.get("type") == "text"
        else ""
        for part in content
    )
