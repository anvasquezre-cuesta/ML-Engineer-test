"""Prepare validated questions for vector retrieval."""

import logging

from app.models.retrieval import EmbeddedQuery
from app.services.errors import EmbeddingResponseError
from app.services.protocols import EmbeddingService, QueryScopeService

logger = logging.getLogger(__name__)


class DocumentQueryPreparationService:
    """Detect explicit scope and embed a question exactly once."""

    def __init__(
        self,
        scope_service: QueryScopeService,
        embedding_service: EmbeddingService,
    ) -> None:
        self._scope_service = scope_service
        self._embedding_service = embedding_service

    def prepare(self, question: str) -> EmbeddedQuery:
        """Return the complete input required by pgvector similarity search."""

        if not question.strip():
            raise ValueError("retrieval question cannot be blank")

        logger.info(
            "Query preparation started: question_length=%s",
            len(question),
        )
        scope = self._scope_service.detect(question)
        embedding = self._embedding_service.embed_query(question)
        if not embedding:
            raise EmbeddingResponseError(
                "embedding service returned an empty query vector"
            )

        logger.info(
            "Query preparation completed: embedding_dimensions=%s, "
            "filter_fields=%s",
            len(embedding),
            sorted(scope.as_metadata_filter()),
        )
        return EmbeddedQuery(
            question=question,
            scope=scope,
            embedding=embedding,
        )
