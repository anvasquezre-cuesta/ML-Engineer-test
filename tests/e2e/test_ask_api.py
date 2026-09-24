"""``POST /api/ask`` over HTTP after a real ingest, with a scripted model."""

import pytest

from app.ports import llm
from tests.e2e import wiring
from tests.fakes import llm as llm_fake

pytestmark = pytest.mark.e2e

PDF = b"%PDF-1.7\nminutes"


def asked(model: llm.Llm, question: str) -> tuple[int, dict[str, object]]:
    """Ingests ``PDF`` as ``minutes.pdf`` and asks ``question``.

    Args:
        model: The language model the app calls.
        question: The question posted to ``/api/ask``.

    Returns:
        The HTTP status and the decoded body of the ask response.
    """
    with wiring.fake_client(model=model, raise_server_exceptions=True) as c:
        c.post(
            "/api/ingest",
            files={"pdf_file": ("minutes.pdf", PDF, "application/pdf")},
        )
        response = c.post("/api/ask", json={"question": question})
    return response.status_code, response.json()


def test_answer_rests_on_the_ingested_chunk_it_cites() -> None:
    model = llm_fake.ScriptedLlm("Anna Berg met Lucas Moreau [1].")

    status, body = asked(model, "Who did Anna Berg meet?")

    assert (status, body) == (
        200,
        {
            "answer": "Anna Berg met Lucas Moreau [1].",
            "sources": ["minutes.pdf#page=1&chunk=0"],
        },
    )
    assert "Dr. Anna Berg met Lucas Moreau" in model.prompts[0].user
