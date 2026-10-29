from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.errors import DomainError, InfrastructureError
from app.infrastructure.settings import Settings
from app.main import create_app
from tests.unit.api.conftest import fake_container


class _RuleBroken(DomainError):
    code = "rule_broken"


class _EngineDown(InfrastructureError):
    code = "engine_down"


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    app = create_app(settings, build_container=fake_container)

    @app.get("/boom/domain")
    def domain() -> None:
        raise _RuleBroken("the rule was broken")

    @app.get("/boom/infra")
    def infra() -> None:
        raise _EngineDown("the engine is down")

    @app.get("/boom/unexpected")
    def unexpected() -> None:
        raise ValueError("secret internal detail")

    return app


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/boom/domain", 422, "rule_broken"),
        ("/boom/infra", 503, "engine_down"),
        ("/boom/unexpected", 500, "internal_error"),
    ],
)
def test_errors_map_to_status_and_body(
    make_client: Callable[..., TestClient], app: FastAPI, path: str, status: int, code: str
) -> None:
    client = make_client(app, raise_server_exceptions=False)

    response = client.get(path, headers={"X-Request-ID": "req-1"})

    assert response.status_code == status
    error = response.json()["error"]
    assert set(error) == {"code", "message", "request_id"}
    assert error["code"] == code
    assert error["request_id"] == "req-1"
    assert "Traceback" not in response.text
    assert "secret internal detail" not in response.text


def test_unhandled_error_is_logged_with_stack_trace(
    make_client: Callable[..., TestClient], app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    client = make_client(app, raise_server_exceptions=False)

    client.get("/boom/unexpected", headers={"X-Request-ID": "req-2"})

    records = [r for r in caplog.records if r.getMessage() == "unhandled_error"]
    assert len(records) == 1
    assert records[0].exc_info is not None


def test_request_validation_error_has_the_same_shape(
    make_client: Callable[..., TestClient], settings: Settings
) -> None:
    app = create_app(settings, build_container=fake_container)

    @app.get("/typed")
    def typed(n: int) -> int:
        return n

    response = make_client(app).get("/typed", params={"n": "abc"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_invalid"
