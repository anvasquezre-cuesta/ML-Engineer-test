from collections.abc import Callable

from fastapi.testclient import TestClient


def test_health_is_ok_with_request_id(make_client: Callable[..., TestClient]) -> None:
    response = make_client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]
