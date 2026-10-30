from fastapi.testclient import TestClient

from app.main import app


def test_ac_ask_page_01_serves_page_that_calls_rag():
    response = TestClient(app).get("/viewer/ask.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/api/ingest" in response.text
    assert "/api/ask" in response.text
