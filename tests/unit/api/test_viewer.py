from collections.abc import Callable

from fastapi.testclient import TestClient


def test_the_audit_viewer_is_served_as_one_html_page(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client().get("/viewer")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = response.text
    assert "pdf.js" in page  # renders the PDF pages
    assert "/api/extract" in page  # and overlays the boxes the API returns
    assert "/api/ingest" in page
    assert "/api/ask" in page


def test_the_root_redirects_to_the_viewer(make_client: Callable[..., TestClient]) -> None:
    response = make_client().get("/", follow_redirects=False)

    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/viewer"
