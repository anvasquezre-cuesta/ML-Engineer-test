import logging

import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_request_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.main")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "Request started: GET /health" in caplog.messages
    assert any(
        message.startswith("Request completed: GET /health returned 200 in")
        for message in caplog.messages
    )
