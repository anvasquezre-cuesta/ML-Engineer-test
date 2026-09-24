"""A missing LLM configuration fails each question, never the startup."""

import pytest

from app import bootstrap
from app import config
from app.adapters.noop_observability import observability as noop
from app.domain import errors
from app.domain import rag


async def test_openai_without_a_key_starts_and_reports_not_configured() -> None:
    model = bootstrap.build_llm(
        config.LlmSettings(provider="openai"), noop.NoopObservability()
    )

    with pytest.raises(errors.LlmNotConfiguredError):
        await model.complete(rag.LlmPrompt("rules", "question"))
