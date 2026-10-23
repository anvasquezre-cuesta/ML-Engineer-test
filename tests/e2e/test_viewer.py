"""The audit viewer page is served and wired to the API (rendering is checked in a browser)."""

from tests.e2e.conftest import ClientFactory


def test_viewer_is_served_as_html(make_client: ClientFactory) -> None:
    response = make_client().get("/viewer")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = response.text
    assert 'fetch("/api/extract"' in page
    assert "pdf.js/4.10.38/pdf.min.mjs" in page  # pinned version
    assert "innerHTML" not in page  # names are untrusted text: only textContent is used
