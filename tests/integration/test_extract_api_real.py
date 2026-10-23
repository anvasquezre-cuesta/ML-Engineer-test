"""``POST /api/extract`` end to end with the production wiring: real Tesseract and spaCy."""

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.integration.conftest import SAMPLES, requires_spacy_model, requires_tesseract

pytestmark = [pytest.mark.integration, requires_tesseract, requires_spacy_model]


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(_env_file=None, log_json=False))) as client:
        yield client


def test_extract_on_company_memo(client: TestClient) -> None:
    names = [
        {"first_name": "María", "last_name": "García"},
        {"first_name": "Robert", "last_name": "Chen"},
        {"first_name": "Bob", "last_name": "Smith"},
    ]

    response = client.post(
        "/api/extract",
        files={"pdf_file": ("memo.pdf", (SAMPLES / "company_memo.pdf").read_bytes())},
        data={"names": json.dumps(names)},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["extracted_names"]) == 8
    robert = next(n for n in body["extracted_names"] if n["name"] == "Robert Chen")
    assert robert["bounding_box"]["page_number"] == 0
    assert robert["bounding_box"]["x"] == pytest.approx(60, abs=3)
    assert robert["bounding_box"]["y"] == pytest.approx(267, abs=3)
    assert {
        (m["extracted_name"], m["matched_name"], m["score"]) for m in body["fuzzy_matches"]
    } == {
        ("Maria Garcia", "María García", 1.0),
        ("Robert Chen", "Robert Chen", 1.0),
    }
