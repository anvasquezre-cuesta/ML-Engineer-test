from tests.e2e.conftest import ClientFactory


def test_health_returns_ok(make_client: ClientFactory) -> None:
    response = make_client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_response_carries_a_generated_request_id(make_client: ClientFactory) -> None:
    response = make_client().get("/health")

    assert len(response.headers["x-request-id"]) == 32


def test_valid_incoming_request_id_is_echoed(make_client: ClientFactory) -> None:
    response = make_client().get("/health", headers={"X-Request-ID": "trace-abc.123"})

    assert response.headers["x-request-id"] == "trace-abc.123"


def test_unsafe_incoming_request_id_is_replaced(make_client: ClientFactory) -> None:
    response = make_client().get("/health", headers={"X-Request-ID": "bad id <script>"})

    assert response.headers["x-request-id"] != "bad id <script>"
    assert len(response.headers["x-request-id"]) == 32
