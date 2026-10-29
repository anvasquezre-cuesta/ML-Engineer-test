import json
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.logging import JsonFormatter


def test_incoming_request_id_is_echoed_and_logged_once(
    make_client: Callable[..., TestClient], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")

    response = make_client().get("/health", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"
    records = [r for r in caplog.records if r.getMessage() == "request_completed"]
    assert len(records) == 1
    payload = json.loads(JsonFormatter().format(records[0]))
    assert payload["event"] == "request_completed"
    assert payload["request_id"] == "abc-123"
    assert payload["status"] == 200
    assert payload["method"] == "GET"
    assert payload["path"] == "/health"
    assert isinstance(payload["duration_ms"], float)


def test_request_id_is_generated_when_absent(make_client: Callable[..., TestClient]) -> None:
    first = make_client().get("/health").headers["X-Request-ID"]
    second = make_client().get("/health").headers["X-Request-ID"]

    assert first
    assert first != second
