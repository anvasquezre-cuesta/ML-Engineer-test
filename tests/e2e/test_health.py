from typing import NoReturn

from app.domain.errors import UpstreamUnavailable
from app.services.health import Check
from tests.e2e.conftest import ClientFactory


def _down() -> NoReturn:
    raise UpstreamUnavailable("connection refused")


def test_health_is_exactly_the_specified_body(make_client: ClientFactory) -> None:
    response = make_client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_stays_ok_when_a_dependency_is_down(make_client: ClientFactory) -> None:
    # Liveness must not flap with dependencies; readiness reports them.
    response = make_client(checks=[Check("vector_store", _down)]).get("/health")

    assert response.json() == {"status": "ok"}


def test_ready_reports_each_check(make_client: ClientFactory) -> None:
    response = make_client().get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["vector_store"]["ok"] is True
    assert body["checks"]["vector_store"]["detail"] == "0 chunks stored"


def test_ready_is_503_when_a_critical_dependency_fails(make_client: ClientFactory) -> None:
    response = make_client(checks=[Check("vector_store", _down)]).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_ready_is_degraded_but_200_when_only_the_llm_fails(make_client: ClientFactory) -> None:
    checks = [Check("vector_store", lambda: "5 chunks"), Check("llm", _down, critical=False)]

    response = make_client(checks=checks).get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["llm"]["ok"] is False


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
