import logging
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import Container
from app.application.ports import AnswerGenerator
from app.domain.chunking import Chunk
from app.domain.errors import LlmRateLimited, LlmTimeout, LlmUnavailable
from app.domain.grounding import NOT_FOUND_ANSWER
from app.infrastructure.openai_answer_generator import OpenAiCompatibleAnswerGenerator
from app.infrastructure.settings import Settings
from app.main import create_app
from app.models.schemas import RAGResponse
from tests.fakes import FakeAnswerGenerator, FakeEmbedder, InMemoryVectorStore
from tests.unit.api.conftest import fake_container

MEMO = Chunk("aaa", "company_memo.pdf", 0, 0, "Robert Chen was promoted to Vice President.")


def _store_with_memo() -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    store.replace_document("aaa", [MEMO], FakeEmbedder().embed_passages([MEMO.text]))
    return store


def _client(
    make_client: Callable[..., TestClient],
    settings: Settings,
    generator: AnswerGenerator,
    store: InMemoryVectorStore | None = None,
) -> TestClient:
    def build(s: Settings) -> Container:
        return fake_container(s, store=store or _store_with_memo(), generator=generator)

    return make_client(create_app(settings, build_container=build))


def test_answer_with_sources_built_from_citations(
    make_client: Callable[..., TestClient], settings: Settings
) -> None:
    client = _client(make_client, settings, FakeAnswerGenerator("Robert Chen [1]."))

    response = client.post("/api/ask", json={"question": "Who was promoted?"})

    assert response.status_code == 200
    assert RAGResponse.model_validate(response.json()) == RAGResponse(
        answer="Robert Chen [1].", sources=["company_memo.pdf, page 0"]
    )


def test_empty_store_answers_not_found_without_the_llm(
    make_client: Callable[..., TestClient], settings: Settings
) -> None:
    generator = FakeAnswerGenerator("never [1].")
    client = _client(make_client, settings, generator, store=InMemoryVectorStore())

    response = client.post("/api/ask", json={"question": "Who was promoted?"})

    assert response.json() == {"answer": NOT_FOUND_ANSWER, "sources": []}
    assert generator.prompts == []


@pytest.mark.parametrize(
    ("generator", "status", "code"),
    [
        (
            FakeAnswerGenerator(error=LlmTimeout("The LLM did not answer in time")),
            503,
            "llm_timeout",
        ),
        (FakeAnswerGenerator(error=LlmRateLimited("rate-limited")), 503, "llm_rate_limited"),
        (FakeAnswerGenerator(error=LlmUnavailable("HTTP 500")), 502, "llm_unavailable"),
        (
            OpenAiCompatibleAnswerGenerator("https://llm.example/v1", None, "m", 5.0, 0),
            503,
            "llm_not_configured",
        ),
    ],
)
def test_llm_failures_map_to_distinct_codes(
    make_client: Callable[..., TestClient],
    settings: Settings,
    generator: AnswerGenerator,
    status: int,
    code: str,
) -> None:
    client = _client(make_client, settings, generator)

    response = client.post("/api/ask", json={"question": "Who was promoted?"})

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"]


@pytest.mark.parametrize("body", [{"question": ""}, {}, {"question": "x" * 2001}])
def test_invalid_body_is_rejected(
    make_client: Callable[..., TestClient], settings: Settings, body: dict[str, str]
) -> None:
    client = _client(make_client, settings, FakeAnswerGenerator())

    response = client.post("/api/ask", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_invalid"


def test_logs_carry_neither_the_question_nor_the_answer(
    make_client: Callable[..., TestClient],
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    client = _client(make_client, settings, FakeAnswerGenerator("Robert Chen [1]."))

    client.post("/api/ask", json={"question": "Who got the secret promotion?"})

    logged = " ".join(repr(record.__dict__) for record in caplog.records)
    assert "secret promotion" not in logged
    assert "Robert Chen" not in logged
