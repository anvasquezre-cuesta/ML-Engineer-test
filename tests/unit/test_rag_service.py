import pytest

from app.services.rag_service import NO_DOCUMENTS_ANSWER, RagService
from tests.fakes import FakeEmbedder, FakeLLM, FakeOcr, InMemoryStore, page_from_lines


@pytest.fixture
def store():
    return InMemoryStore()


@pytest.fixture
def rag(store):
    ocr = FakeOcr([page_from_lines(0, ["alpha beta gamma delta epsilon zeta eta theta"])])
    return RagService(ocr, FakeEmbedder(), store, FakeLLM("grounded"), 20, 5, 3)


def test_second_ingest_does_not_overwrite_the_first(rag, store):
    first = rag.ingest(b"same bytes", "a.pdf")
    second = rag.ingest(b"same bytes", "a.pdf")
    assert first == second > 0
    assert len(store.rows) == first + second
    assert len(set(store.rows)) == len(store.rows)


async def test_sources_are_exactly_what_was_retrieved(rag, store):
    rag.ingest(b"x", "memo.pdf")
    response = await rag.ask("what is alpha?")
    assert response.answer == "grounded"
    assert response.sources
    assert set(response.sources) <= {source for _, source in store.rows.values()}
    assert all("memo.pdf#" in s and "#page0#chunk" in s for s in response.sources)


async def test_context_is_passed_to_the_llm(rag):
    rag.ingest(b"x", "memo.pdf")
    await rag.ask("anything")
    system, user = rag.llm.prompts[-1]
    assert "only the context" in system
    assert "alpha" in user and "anything" in user


async def test_empty_store_short_circuits_without_calling_llm(rag):
    response = await rag.ask("hello?")
    assert response.answer == NO_DOCUMENTS_ANSWER
    assert response.sources == []
    assert rag.llm.prompts == []
