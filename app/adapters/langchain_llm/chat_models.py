"""Builds the configured LangChain chat model with explicit credentials."""

from botocore import config as botocore_config
import langchain_aws
from langchain_core.language_models import chat_models
import langchain_openai

from app import config
from app.domain import errors

OPENAI_BASE_URL = "https://api.openai.com/v1"


def build_chat_model(
    settings: config.LlmSettings,
) -> chat_models.BaseChatModel:
    """Builds the chat model of the configured provider.

    Credentials, timeouts and retry budgets come only from ``settings``;
    the SDKs never fall back to their own environment variables. Retries are
    counted after the first attempt, so Bedrock gets
    ``max_retries + 1`` total attempts.

    Args:
        settings: Provider, model, credentials and limits.

    Returns:
        The chat model.

    Raises:
        errors.LlmNotConfiguredError: If the OpenAI provider has no API key.
    """
    if settings.provider == "openai":
        if settings.openai_api_key is None:
            raise errors.LlmNotConfiguredError(
                "DOCINTEL_LLM__OPENAI_API_KEY is not set."
            )
        return langchain_openai.ChatOpenAI(
            model_name=settings.openai_model,
            openai_api_key=settings.openai_api_key,
            openai_api_base=settings.openai_base_url or OPENAI_BASE_URL,
            openai_organization="",
            openai_proxy="",
            request_timeout=settings.timeout_s,
            max_retries=settings.max_retries,
            temperature=settings.openai_temperature,
            max_tokens=settings.max_tokens,
            reasoning_effort=settings.reasoning_effort,
        )
    retries = botocore_config.Config(
        retries={
            "total_max_attempts": settings.max_retries + 1,
            "mode": "standard",
        },
        connect_timeout=settings.timeout_s,
        read_timeout=settings.timeout_s,
    )
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        return langchain_aws.ChatBedrockConverse(
            model_id=settings.bedrock_model,
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            aws_session_token=None,
            config=retries,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        )
    # No keys: a named profile, or the default chain (the ECS task role).
    return langchain_aws.ChatBedrockConverse(
        model_id=settings.bedrock_model,
        region_name=settings.aws_region,
        credentials_profile_name=settings.aws_profile or None,
        config=retries,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )
