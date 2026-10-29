import logging

import pytest

from app.application.retrieve_chunks import RetrieveChunks
from app.domain.chunking import Chunk
from app.domain.errors import VectorStoreUnavailable
from tests.fakes import FakeEmbedder, FakeReranker, InMemoryVectorStore


def _store(*texts: str) -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    chunks = [Chunk("doc", "memo.pdf", 0, i, text) for i, text in enumerate(texts)]
    store.replace_document("doc", chunks, FakeEmbedder().embed_passages(texts))
    return store


def _retrieve(
    store: InMemoryVectorStore,
    reranker: FakeReranker,
    embedder: FakeEmbedder | None = None,
    candidates: int = 10,
    top_k: int = 5,
) -> RetrieveChunks:
    return RetrieveChunks(
        embedder=embedder or FakeEmbedder(),
        store=store,
        reranker=reranker,
        candidates=candidates,
        top_k=top_k,
    )


def test_dense_and_exact_term_candidates_both_reach_the_reranker() -> None:
    # A is the nearest by letters (dense) but lacks the word; only B contains it (BM25).
    a_text = "konow kook"
    b_text = "Okonkwo approved the large budget items yesterday afternoon"
    reranker = FakeReranker()

    _retrieve(_store(a_text, b_text), reranker, candidates=1).execute("okonkwo")

    assert len(reranker.calls) == 1
    assert sorted(reranker.calls[0]) == sorted([a_text, b_text])


def test_the_best_reranked_chunks_are_returned_best_first() -> None:
    texts = [f"chunk number {n}" for n in range(8)]
    scores = {text: float(n % 5) + n / 10 for n, text in enumerate(texts)}
    reranker = FakeReranker(scores)

    retrieved = _retrieve(_store(*texts), reranker, top_k=5).execute("chunk number")

    expected = sorted(texts, key=lambda text: -scores[text])[:5]
    assert [r.chunk.text for r in retrieved] == expected
    assert [r.score for r in retrieved] == sorted((r.score for r in retrieved), reverse=True)


def test_low_rerank_scores_still_reach_the_llm() -> None:
    # No score cut-off: whether the passages answer the question is the LLM's call.
    reranker = FakeReranker(default=-7.5)

    retrieved = _retrieve(_store("budget review"), reranker).execute("budget")

    assert [r.chunk.text for r in retrieved] == ["budget review"]
    assert retrieved[0].score == -7.5


def test_empty_store_returns_nothing_without_calling_the_models() -> None:
    embedder, reranker = FakeEmbedder(), FakeReranker()

    retrieved = _retrieve(InMemoryVectorStore(), reranker, embedder=embedder).execute("budget")

    assert retrieved == ()
    assert embedder.question_calls == 0
    assert reranker.calls == []


def test_fewer_chunks_than_top_k_returns_them_all() -> None:
    retrieved = _retrieve(_store("a budget", "b budget", "c budget"), FakeReranker()).execute(
        "budget"
    )

    assert len(retrieved) == 3


def test_store_failure_propagates() -> None:
    store = InMemoryVectorStore(error=VectorStoreUnavailable("down"))

    with pytest.raises(VectorStoreUnavailable):
        _retrieve(store, FakeReranker()).execute("budget")


def test_completion_log_has_counts_but_no_question_or_chunk_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    _retrieve(_store("Margaret approved the budget"), FakeReranker()).execute("secret question")

    records = [r for r in caplog.records if r.getMessage() == "retrieval_completed"]
    assert len(records) == 1
    fields = records[0].__dict__
    assert fields["returned_count"] == 1
    assert "secret question" not in repr(fields)
    assert "Margaret" not in repr(fields)
