import logging

import pytest
from pydantic import SecretStr

from app.infrastructure.settings import Settings
from app.main import _llm_api_key


@pytest.mark.parametrize("key", [None, ""])
def test_missing_or_empty_llm_key_is_not_configured_and_warned(
    key: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    settings = Settings(_env_file=None, llm_api_key=None if key is None else SecretStr(key))

    assert _llm_api_key(settings) is None
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [
        "llm_not_configured"
    ]


def test_configured_llm_key_is_passed_through_and_never_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(_env_file=None, llm_api_key=SecretStr("gsk_secret"))

    assert _llm_api_key(settings) == "gsk_secret"
    assert "gsk_secret" not in caplog.text
