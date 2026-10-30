import json
import shutil
from pathlib import Path

import pytest
import spacy
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

pytestmark = pytest.mark.skipif(
    shutil.which("tesseract") is None or not spacy.util.is_package("en_core_web_sm"),
    reason="tesseract or en_core_web_sm not installed",
)

MEMO = Path(__file__).parents[2] / "sample_pdfs" / "company_memo.pdf"
# Query list of the fuzzy notebook: accents, a near miss, a duplicate, an absent name.
NAMES = [
    {"first_name": "Robert", "last_name": "Chen"},
    {"first_name": "María", "last_name": "García"},
    {"first_name": "Mario", "last_name": "Garcia"},
    {"first_name": "Robert", "last_name": "Chen"},
    {"first_name": "Juan", "last_name": "Pérez"},
]


@pytest.fixture
def threshold_090(monkeypatch):
    monkeypatch.setenv("FUZZY_THRESHOLD", "0.90")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_ac_api_06_company_memo(threshold_090):
    with MEMO.open("rb") as pdf:
        files = {"pdf_file": ("company_memo.pdf", pdf, "application/pdf")}
        response = TestClient(app).post(
            "/api/extract", files=files, data={"names": json.dumps(NAMES)}
        )

    assert response.status_code == 200
    body = response.json()
    assert [n["name"] for n in body["extracted_names"]] == [
        "Margaret Thompson",
        "Robert Chen",
        "Sarah Williams",
        "James Anderson",
        "Maria Garcia",
        "David Nakamura",
        "Patricia Okonkwo",
        "Margaret Thompson",
    ]
    assert {n["bounding_box"]["page_number"] for n in body["extracted_names"]} == {0}
    assert [tuple(m.values()) for m in body["fuzzy_matches"]] == [
        ("Maria Garcia", "María García", 1.0),
        ("Robert Chen", "Robert Chen", 1.0),
        ("Maria Garcia", "Mario Garcia", 0.9167),
    ]
