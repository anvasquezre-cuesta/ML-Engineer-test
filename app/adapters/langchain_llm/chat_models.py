"""Builds the configured LangChain chat model with explicit credentials."""

from langchain_core.language_models import chat_models

from app import config


def build_chat_model(  # noqa: DOC501, DOC503
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
    raise NotImplementedError
