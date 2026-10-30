from fastapi.testclient import TestClient

from app.main import app

PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/6.4.299/"


def test_ac_view_01_page_pins_pdfjs_and_calls_extract():
    response = TestClient(app).get("/viewer/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert PDFJS + "pdf.min.mjs" in response.text
    assert PDFJS + "pdf.worker.min.mjs" in response.text
    assert "/api/extract" in response.text
