from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, log_json=False)))


def test_health_returns_ok() -> None:
    with _client() as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_response_carries_a_generated_request_id() -> None:
    with _client() as client:
        response = client.get("/health")

    assert len(response.headers["x-request-id"]) == 32


def test_valid_incoming_request_id_is_echoed() -> None:
    with _client() as client:
        response = client.get("/health", headers={"X-Request-ID": "trace-abc.123"})

    assert response.headers["x-request-id"] == "trace-abc.123"


def test_unsafe_incoming_request_id_is_replaced() -> None:
    with _client() as client:
        response = client.get("/health", headers={"X-Request-ID": "bad id <script>"})

    assert response.headers["x-request-id"] != "bad id <script>"
    assert len(response.headers["x-request-id"]) == 32
