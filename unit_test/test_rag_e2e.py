"""Hermetic HTTP-to-response coverage of the complete RAG query path."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

import httpx
import pytest
from flashrank import RerankRequest
from langchain_core.documents import Document

from app.api.dependencies import get_rag_service
from app.config import Settings
from app.main import app
from app.services.candidate_selection_service import TopRankedCandidateSelector
from app.services.embedding_service import LangChainOpenAIEmbeddingService
from app.services.evidence_assessment_service import ThresholdEvidenceAssessmentService
from app.services.grounded_context_service import JSONGroundedContextService
from app.services.llm_service import LiteLLMAnswerGenerationService
from app.services.query_preparation_service import DocumentQueryPreparationService
from app.services.query_scope_service import ExplicitQueryScopeService
from app.services.rag_service import DocumentRAGService
from app.services.reranker_service import FlashRankCrossEncoderReranker
from app.services.source_service import CitationSourceService
from app.services.vector_service import LangChainPostgresVectorStore


class FakeEmbeddingProvider:
    """Replace the external embedding API, retaining its production adapter."""

    def __init__(self) -> None:
        self.query_calls: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("the ask path must not embed documents")

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return [0.1, 0.2, 0.3]


class FakeLangChainVectorStore:
    """Replace PostgreSQL/pgvector, retaining retrieval and metadata checks."""

    def __init__(self, results: list[tuple[Document, float]]) -> None:
        self.results = results
        self.filters: list[dict | None] = []

    def add_embeddings(
        self,
        texts: Sequence[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        ids: list[str],
    ) -> list[str]:
        raise AssertionError("the ask path must not write vectors")

    def similarity_search_with_score_by_vector(
        self,
        embedding: list[float],
        k: int | None = None,
        filter: dict | None = None,
    ) -> list[tuple[Document, float]]:
        assert embedding == [0.1, 0.2, 0.3]
        assert k == 10
        self.filters.append(filter)
        return self.results


class FakeCrossEncoder:
    """Replace model inference, retaining real reranker validation and sorting."""

    def __init__(self, scores: Mapping[str, float]) -> None:
        self.scores = scores
        self.calls = 0

    def rerank(self, request: RerankRequest) -> Sequence[Mapping[str, object]]:
        self.calls += 1
        return [
            {"id": passage["id"], "score": self.scores[str(passage["id"])]}
            for passage in request.passages
        ]


class FakeCompletionProvider:
    """Replace the paid LLM call, retaining prompt and response validation."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return {
            "choices": [
                {
                    "message": {"content": self.answer},
                    "finish_reason": "stop",
                }
            ]
        }


@dataclass(frozen=True)
class RAGHarness:
    service: DocumentRAGService
    embedding: FakeEmbeddingProvider
    vector_store: FakeLangChainVectorStore
    reranker: FakeCrossEncoder
    completion: FakeCompletionProvider


def make_document(
    *,
    chunk_index: int,
    text: str,
    section: str,
    page_start: int,
) -> Document:
    document_id = UUID("12345678-1234-5678-1234-567812345678")
    chunk_id = f"{document_id}:{chunk_index:06d}"
    embedding_text = (
        "Document: Board of Directors - Meeting Minutes\n"
        f"Section: {section}\n\n{text}"
    )
    return Document(
        id=chunk_id,
        page_content=text,
        metadata={
            "document_id": document_id,
            "filename": "meeting_minutes.pdf",
            "document_type": "meeting_minutes",
            "document_title": "Board of Directors - Meeting Minutes",
            "section": section,
            "page_start": page_start,
            "page_end": page_start,
            "chunk_index": chunk_index,
            "word_count": len(text.split()),
            "embedding_text": embedding_text,
        },
    )


def build_harness(
    *,
    search_results: list[tuple[Document, float]],
    reranker_scores: Mapping[str, float],
    generated_answer: str,
) -> RAGHarness:
    settings = Settings(
        _env_file=None,
        embedding_dimensions=3,
        retrieval_candidate_count=10,
        selected_candidate_count=3,
        evidence_min_relevance_score=0.5,
        llm_model_name="openai/test-model",
        llm_max_tokens=200,
        llm_max_retries=0,
    )
    embedding = FakeEmbeddingProvider()
    embedding_service = LangChainOpenAIEmbeddingService(settings, provider=embedding)
    vector_store = FakeLangChainVectorStore(search_results)
    reranker = FakeCrossEncoder(reranker_scores)
    completion = FakeCompletionProvider(generated_answer)
    service = DocumentRAGService(
        query_preparation_service=DocumentQueryPreparationService(
            scope_service=ExplicitQueryScopeService(),
            embedding_service=embedding_service,
        ),
        vector_store=LangChainPostgresVectorStore(
            settings,
            embedding_provider=embedding_service.provider,
            vector_store=vector_store,
            sleeper=lambda _: None,
        ),
        reranker_service=FlashRankCrossEncoderReranker(
            settings,
            ranker=reranker,
        ),
        candidate_selection_service=TopRankedCandidateSelector(settings),
        evidence_assessment_service=ThresholdEvidenceAssessmentService(settings),
        grounded_context_service=JSONGroundedContextService(),
        answer_generation_service=LiteLLMAnswerGenerationService(
            settings,
            completion_provider=completion,
        ),
        source_construction_service=CitationSourceService(),
    )
    return RAGHarness(
        service=service,
        embedding=embedding,
        vector_store=vector_store,
        reranker=reranker,
        completion=completion,
    )


async def post_question(harness: RAGHarness, question: str) -> httpx.Response:
    app.dependency_overrides[get_rag_service] = lambda: harness.service
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post("/api/ask", json={"question": question})
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_complete_http_rag_path_returns_only_reranked_grounded_source() -> None:
    financial = make_document(
        chunk_index=0,
        text="Revenue increased 12% year-over-year.",
        section="Financial Report",
        page_start=0,
    )
    legal = make_document(
        chunk_index=1,
        text="Kevin O'Brien coordinated the legal review with external counsel.",
        section="New Business",
        page_start=1,
    )
    harness = build_harness(
        # Vector distance favors the wrong passage; the reranker must correct it.
        search_results=[(financial, 0.05), (legal, 0.20)],
        reranker_scores={str(financial.id): 0.20, str(legal.id): 0.95},
        generated_answer="Kevin O'Brien coordinated the legal review [S1].",
    )
    question = (
        "  According to meeting_minutes.pdf, who coordinated the legal review?  "
    )

    response = await post_question(harness, question)

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Kevin O'Brien coordinated the legal review [S1].",
        "sources": ["[S1] meeting_minutes.pdf · page 2 · New Business"],
    }
    assert harness.embedding.query_calls == [question.strip()]
    assert harness.vector_store.filters == [
        {
            "filename": {"$ilike": r"meeting\_minutes.pdf"},
            "document_type": "meeting_minutes",
        }
    ]
    assert harness.reranker.calls == 1
    assert len(harness.completion.calls) == 1
    messages = harness.completion.calls[0]["messages"]
    assert isinstance(messages, list)
    assert "New Business" in messages[1]["content"]
    assert "Financial Report" not in messages[1]["content"]


@pytest.mark.asyncio
async def test_complete_http_rag_path_rejects_fabricated_llm_source() -> None:
    legal = make_document(
        chunk_index=1,
        text="Kevin O'Brien coordinated the legal review with external counsel.",
        section="New Business",
        page_start=1,
    )
    harness = build_harness(
        search_results=[(legal, 0.1)],
        reranker_scores={str(legal.id): 0.95},
        generated_answer="Kevin O'Brien coordinated the review [S99].",
    )

    response = await post_question(
        harness,
        "According to meeting_minutes.pdf, who coordinated the legal review?",
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "answer generation service returned an invalid response"
    }
    assert "S99" not in response.text
    assert len(harness.completion.calls) == 1
