"""Gate B: ingest the samples, then ask through HTTP with the real embedder, Chroma and LLM.

Skipped unless Tesseract is installed and the configured LLM endpoint answers.
"""

import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import RAGSettings, Settings
from app.main import create_app
from app.services.ask import NOT_FOUND_ANSWER
from tests.integration.conftest import SAMPLES, requires_spacy_model, requires_tesseract

LLM_URL = Settings(_env_file=None).llm.base_url


def _llm_available() -> bool:
    try:
        with urllib.request.urlopen(f"{LLM_URL}/models", timeout=3) as response:
            return bool(response.status == 200)
    except OSError:
        return False


pytestmark = [
    pytest.mark.integration,
    requires_tesseract,
    requires_spacy_model,
    pytest.mark.skipif(not _llm_available(), reason=f"no LLM endpoint at {LLM_URL}"),
]


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    chroma = Path(tmp_path_factory.mktemp("chroma"))
    settings = Settings(_env_file=None, log_json=False, rag=RAGSettings(chroma_path=str(chroma)))
    with TestClient(create_app(settings)) as client:
        for name in ("company_memo.pdf", "meeting_minutes.pdf", "research_report.pdf"):
            response = client.post(
                "/api/ingest", files={"pdf_file": (name, (SAMPLES / name).read_bytes())}
            )
            assert response.status_code == 200
        yield client


def test_answerable_question_is_answered_from_the_right_page(client: TestClient) -> None:
    response = client.post(
        "/api/ask", json={"question": "Who was promoted to Vice President of Engineering?"}
    )

    body = response.json()
    assert response.status_code == 200
    assert "Robert Chen" in body["answer"]
    assert body["sources"] == ["company_memo.pdf#page=1"]


def test_unanswerable_question_is_refused_without_the_llm(client: TestClient) -> None:
    response = client.post("/api/ask", json={"question": "What is the 2025 marketing budget?"})

    assert response.json() == {"answer": NOT_FOUND_ANSWER, "sources": []}


def test_answer_on_a_lower_ranked_page_reaches_the_model(client: TestClient) -> None:
    response = client.post(
        "/api/ask", json={"question": "When is the next board meeting scheduled?"}
    )

    body = response.json()
    assert "meeting_minutes.pdf#page=2" in body["sources"]
    assert "March 18" in body["answer"]
