from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.domain.grounding import NOT_FOUND_ANSWER
from app.infrastructure.settings import Settings
from app.main import create_app
from tests.conftest import SAMPLE_PAGE_COUNTS, sample_bytes

pytestmark = pytest.mark.integration


def _ingested_client(
    settings: Settings, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[TestClient]:
    """An app with its own temporary vector store holding the three samples."""
    store = tmp_path_factory.mktemp("chroma")
    app = create_app(settings.model_copy(update={"vector_store_path": str(store)}))
    with TestClient(app) as client:
        for name in SAMPLE_PAGE_COUNTS:
            response = client.post(
                "/api/ingest", files={"pdf_file": (name, sample_bytes(name), "application/pdf")}
            )
            assert response.status_code == 200, response.text
        yield client


@pytest.fixture(scope="module")
def keyless_client(
    env_settings: Settings, tesseract_cmd: str | None, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[TestClient]:
    settings = env_settings.model_copy(update={"llm_api_key": None})
    yield from _ingested_client(settings, tmp_path_factory)


@pytest.fixture(scope="module")
def live_client(
    env_settings: Settings, tesseract_cmd: str | None, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[TestClient]:
    key = env_settings.llm_api_key
    if key is None or not key.get_secret_value():
        pytest.skip("Set DOCINTEL_LLM_API_KEY to run the live LLM test")
    yield from _ingested_client(env_settings, tmp_path_factory)


def test_answerable_question_without_a_key_is_503(keyless_client: TestClient) -> None:
    response = keyless_client.post(
        "/api/ask", json={"question": "Who was promoted to Vice President of Engineering?"}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_not_configured"


def test_live_answer_cites_the_page_that_states_it(live_client: TestClient) -> None:
    response = live_client.post(
        "/api/ask", json={"question": "Who was promoted to Vice President of Engineering?"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "Robert Chen" in body["answer"]
    assert body["sources"] == ["company_memo.pdf, page 0"]


def test_live_simple_question_is_answered_even_with_a_low_rerank_score(
    live_client: TestClient,
) -> None:
    # Regression: a rerank-score gate once answered "not found" here although the memo
    # says "Margaret Thompson, CEO" — the passages now always reach the LLM.
    response = live_client.post("/api/ask", json={"question": "Who is the CEO of the company?"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert "Margaret Thompson" in body["answer"]
    assert "company_memo.pdf, page 0" in body["sources"]


def test_live_unanswerable_question_is_not_found(live_client: TestClient) -> None:
    response = live_client.post(
        "/api/ask", json={"question": "What is the company's parental leave policy?"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"answer": NOT_FOUND_ANSWER, "sources": []}
