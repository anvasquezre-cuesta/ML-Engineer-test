"""Retrieval quality on the samples: relevance, metrics and the gate run."""

from collections.abc import Mapping
from collections.abc import Sequence
import dataclasses
import statistics

import pytrec_eval
import qdrant_client

from app import bootstrap
from app import config
from app.adapters.fastembed_embedding import embedding
from app.adapters.fastembed_sparse import sparse_embedding
from app.adapters.qdrant import vector_store as qdrant_store
from app.adapters.text_chunker import sentence
from app.domain import rag
from evaluation import dataset

RANK_DEPTH = 10


@dataclasses.dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    """Mean retrieval quality over the judged questions.

    Attributes:
        ndcg_at_10: Normalized discounted cumulative gain of the top 10.
        mrr_at_10: Mean reciprocal rank of the first relevant chunk in the
            top 10.
        recall_at_k: Share of relevant chunks within the top ``k``.
        k: The cut-off of ``recall_at_k``, the configured ``top_k``.
    """

    ndcg_at_10: float
    mrr_at_10: float
    recall_at_k: float
    k: int


def chunk_id(chunk: rag.Chunk) -> str:
    """Identifies a chunk independently of the vector store.

    Args:
        chunk: The chunk.

    Returns:
        ``document#page#index``.
    """
    return f"{chunk.document_key}#{chunk.page_number}#{chunk.chunk_index}"


def relevant_chunks(
    question: dataset.Question, chunks: Sequence[rag.Chunk]
) -> set[str]:
    """Finds the chunks that state a question's answer.

    A chunk is relevant when it is on the evidence's document and page and
    contains the evidence quote, whitespace ignored, so the result does not
    depend on where the chunker cuts.

    Args:
        question: The question and its evidence.
        chunks: Every chunk of the sample documents.

    Returns:
        The ids (``document#page#index``) of the relevant chunks.
    """
    return {
        chunk_id(chunk)
        for chunk in chunks
        for evidence in question.evidence
        if chunk.document_key == evidence.document
        and chunk.page_number == evidence.page
        and _squash(evidence.quote) in _squash(chunk.text)
    }


def score(
    rankings: Mapping[str, Sequence[str]],
    relevant: Mapping[str, set[str]],
    k: int,
) -> RetrievalMetrics:
    """Scores ranked chunk ids against the relevant ones with pytrec_eval.

    Args:
        rankings: Chunk ids per question id, best first.
        relevant: Relevant chunk ids per question id.
        k: Recall cut-off.

    Returns:
        The mean metrics over the questions in ``relevant``.
    """
    qrels = {q: dict.fromkeys(ids, 1) for q, ids in relevant.items()}
    ranked = _evaluate(
        qrels, rankings, RANK_DEPTH, {"ndcg_cut.10", "recip_rank"}
    )
    recalled = _evaluate(qrels, rankings, k, {f"recall.{k}"})
    return RetrievalMetrics(
        ndcg_at_10=statistics.mean(m["ndcg_cut_10"] for m in ranked.values()),
        mrr_at_10=statistics.mean(m["recip_rank"] for m in ranked.values()),
        recall_at_k=statistics.mean(
            m[f"recall_{k}"] for m in recalled.values()
        ),
        k=k,
    )


async def evaluate_samples(
    settings: config.Settings,
) -> RetrievalMetrics:
    """Measures hybrid retrieval on the frozen sample OCR text.

    The pages are chunked, embedded and searched with the service's own
    chunker, FastEmbed models and Qdrant adapter (in memory), at the
    configured ``top_k``.

    Args:
        settings: The service configuration.

    Returns:
        The metrics over the answerable sample questions.
    """
    dense = embedding.FastEmbedEmbedding.load(settings.embeddings)
    sparse = sparse_embedding.FastEmbedSparseEmbedding.load(settings.embeddings)
    chunker = sentence.SentenceTextChunker(
        settings.chunking.chunk_size, settings.chunking.chunk_overlap
    )
    chunks = [
        chunk
        for page in dataset.pages()
        for chunk in chunker.split(
            rag.SourcePage(page.document, "frozen", page.page, page.text)
        )
    ]
    store = qdrant_store.QdrantVectorStore(
        qdrant_client.AsyncQdrantClient(location=":memory:"),
        settings.qdrant,
        collection=bootstrap.collection_name(
            "eval", dense.model_name, sparse.model_name
        ),
        dimension=dense.dimension,
    )
    texts = [chunk.text for chunk in chunks]
    await store.upsert(
        [
            rag.EmbeddedChunk(chunk, vector, terms)
            for chunk, vector, terms in zip(
                chunks,
                dense.embed_documents(texts),
                sparse.embed_documents(texts),
                strict=True,
            )
        ]
    )
    top_k = settings.qdrant.top_k
    answerable = [q for q in dataset.questions() if q.evidence]
    rankings = {}
    for question in answerable:
        query = rag.SearchQuery(
            dense.embed_query(question.question),
            sparse.embed_query(question.question),
        )
        hits = await store.hybrid_search(query, max(RANK_DEPTH, top_k))
        rankings[question.id] = [chunk_id(hit.chunk) for hit in hits]
    relevant = {q.id: relevant_chunks(q, chunks) for q in answerable}
    return score(rankings, relevant, top_k)


def _squash(text: str) -> str:
    """Collapses whitespace so line breaks do not hide a quote.

    Args:
        text: Any text.

    Returns:
        The text with single spaces.
    """
    return " ".join(text.split())


def _evaluate(
    qrels: Mapping[str, Mapping[str, int]],
    rankings: Mapping[str, Sequence[str]],
    depth: int,
    measures: set[str],
) -> dict[str, dict[str, float]]:
    """Runs pytrec_eval on the top ``depth`` of each ranking.

    pytrec_eval ranks by score, so each id gets a score that falls with its
    position.

    Args:
        qrels: Relevance per question and chunk id.
        rankings: Chunk ids per question id, best first.
        depth: How many ranked ids count.
        measures: pytrec_eval measure names.

    Returns:
        The measures per question.
    """
    run = {
        q: {cid: float(len(ids) - i) for i, cid in enumerate(ids[:depth])}
        for q, ids in rankings.items()
        if q in qrels
    }
    evaluator = pytrec_eval.RelevanceEvaluator(dict(qrels), measures)
    results: dict[str, dict[str, float]] = evaluator.evaluate(run)
    return results
