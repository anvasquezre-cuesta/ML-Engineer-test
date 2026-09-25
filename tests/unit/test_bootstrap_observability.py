"""Tracing is optional: missing Langfuse keys never stop the service."""

import pydantic
import pytest

from app import bootstrap
from app import config
from app.adapters.noop_observability import observability as noop


@pytest.mark.parametrize(
    ("public", "secret"),
    [(None, None), ("pk-lf-1", None), (None, "sk-lf-1")],
)
def test_without_both_keys_tracing_is_off_and_nothing_raises(
    public: str | None, secret: str | None
) -> None:
    settings = config.LlmObservabilitySettings(
        langfuse_public_key=pydantic.SecretStr(public) if public else None,
        langfuse_secret_key=pydantic.SecretStr(secret) if secret else None,
    )

    tracing = bootstrap.build_observability(settings)

    assert isinstance(tracing, noop.NoopObservability)
