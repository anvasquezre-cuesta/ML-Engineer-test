from dataclasses import replace

from fastapi.testclient import TestClient

from app.api.dependencies import Container
from app.infrastructure.settings import Settings
from app.main import create_app
from tests.unit.api.conftest import fake_container


def test_shutdown_releases_the_containers_resources(settings: Settings) -> None:
    released: list[str] = []

    def build(s: Settings) -> Container:
        return replace(fake_container(s), on_shutdown=(lambda: released.append("store"),))

    with TestClient(create_app(settings, build_container=build)) as client:
        client.get("/health")
        assert released == []

    assert released == ["store"]
