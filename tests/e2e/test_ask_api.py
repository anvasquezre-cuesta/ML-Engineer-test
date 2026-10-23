"""``POST /api/ask`` through HTTP, and the extract -> ingest -> ask path, with fakes.

The fake document's only line is "Approved by: Robert Chen, CTO"; the fake
embedder scores by shared words, so a question reusing those words is answerable.
"""

from app.domain.errors import UpstreamUnavailable
from app.services.ask import NOT_FOUND_ANSWER
from tests.e2e.conftest import PDF, ClientFactory
from tests.fakes import FakeLLM

ANSWERABLE = "Who approved, Robert Chen CTO?"


class DownLLM(FakeLLM):
    def complete(self, system: str, user: str) -> str:
        raise UpstreamUnavailable("The language model is unavailable: connection refused")


def _ingest(client: object) -> None:
    response = client.post(  # type: ignore[attr-defined]
        "/api/ingest", files={"pdf_file": ("memo.pdf", PDF, "application/pdf")}
    )
    assert response.status_code == 200


def test_extract_ingest_ask_end_to_end(make_client: ClientFactory) -> None:
    llm = FakeLLM("Robert Chen approved it.")
    client = make_client(llm=llm)

    extracted = client.post(
        "/api/extract",
        files={"pdf_file": ("memo.pdf", PDF, "application/pdf")},
        data={"names": '[{"first_name": "Robert", "last_name": "Chen"}]'},
    )
    _ingest(client)
    asked = client.post("/api/ask", json={"question": ANSWERABLE})

    assert extracted.json()["fuzzy_matches"][0]["score"] == 1.0
    assert asked.status_code == 200
    assert asked.json() == {"answer": "Robert Chen approved it.", "sources": ["memo.pdf#page=1"]}
    (_, prompt) = llm.calls[0]
    assert "Approved by: Robert Chen, CTO" in prompt


def test_unanswerable_question_is_not_found_without_llm_call(make_client: ClientFactory) -> None:
    llm = FakeLLM()
    client = make_client(llm=llm)
    _ingest(client)

    response = client.post("/api/ask", json={"question": "What is the 2025 marketing budget?"})

    assert response.json() == {"answer": NOT_FOUND_ANSWER, "sources": []}
    assert llm.calls == []


def test_asking_before_any_ingest_is_not_found(make_client: ClientFactory) -> None:
    response = make_client().post("/api/ask", json={"question": ANSWERABLE})

    assert response.status_code == 200
    assert response.json()["sources"] == []


def test_llm_down_is_503_with_request_id(make_client: ClientFactory) -> None:
    client = make_client(llm=DownLLM())
    _ingest(client)

    response = client.post("/api/ask", json={"question": ANSWERABLE})

    assert response.status_code == 503
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_request_body_is_validated(make_client: ClientFactory) -> None:
    client = make_client()

    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/ask", json={"question": "   "}).status_code == 422
    assert client.post("/api/ask", json={"question": "x" * 2001}).status_code == 422
    assert client.post("/api/ask", json={}).status_code == 422
    assert client.post("/api/ask", content=b"not json").status_code == 422
