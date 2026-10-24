"""ATDD red-phase tests for story 3.1: Audit viewer overlay.

Criteria from plan:
- AC-1: GET /viewer/index.html returns 200, text/html, extract-and-overlay UI present
- AC-2 (auto part): viewer.js contains display-scale expression (getViewport + clientWidth)
- AC-3: page contains #errorBanner and CDN-failure handler
- AC-4: DIS_STATIC_DIR env override honored by mount
- Code-map: mount uses check_dir=False (unknown static path → 404, not 500)
"""
import os

import pytest

from fastapi.testclient import TestClient


@pytest.fixture
def app():
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_ac1_viewer_index_served_200_html(client):
    r = client.get("/viewer/index.html")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    # body should contain extract-and-overlay UI markers
    assert "extract" in r.text.lower() or "overlay" in r.text.lower()


def test_ac2_viewer_js_contains_display_scale_expression(client):
    r = client.get("/viewer/viewer.js")
    assert r.status_code == 200
    text = r.text
    assert "getViewport" in text
    assert "clientWidth" in text


def test_ac3_page_has_error_banner_and_cdn_failure_handler(client):
    r_html = client.get("/viewer/index.html")
    r_js = client.get("/viewer/viewer.js")
    # banner element present in HTML
    assert "errorBanner" in r_html.text
    # CDN-failure handler present in JS (try/catch or .onerror on pdf.js script)
    js = r_js.text
    assert "onerror" in js or ("try" in js and "catch" in js and "pdf" in js.lower())


def test_ac4_static_dir_env_override():
    """Mount directory must come from Settings (DIS_STATIC_DIR), not hardcoded."""
    from app.core.config import reset_settings, get_settings
    reset_settings()
    os.environ["DIS_STATIC_DIR"] = "/tmp/fake_static_dir_for_test"
    try:
        s = get_settings()
        assert s.static_dir == "/tmp/fake_static_dir_for_test", \
            f"static_dir was {s.static_dir}, expected overridden value"
    finally:
        del os.environ["DIS_STATIC_DIR"]
        reset_settings()


def test_mount_check_dir_false_unknown_path_404(client):
    """Mount with check_dir=False → unknown path returns 404, not 500."""
    r = client.get("/viewer/does-not-exist.html")
    assert r.status_code == 404
