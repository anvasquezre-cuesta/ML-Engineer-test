"""LangChain PostgreSQL/pgvector persistence adapter."""

import logging
from collections.abc import Callable, Sequence
from time import sleep
from typing import Protocol, TypeVar, cast

import asyncpg
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import Column, PGEngine, PGVectorStore
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.config import Settings
from app.models.ingestion import ChunkMetadata, EmbeddedChunk
from app.models.retrieval import EmbeddedQuery, RetrievedChunk, VectorSearchResult
from app.services.embedding_service import EmbeddingProvider
from app.services.errors import (
    VectorStoreConfigurationError,
    VectorStoreOperationError,
    VectorStoreRetrievalError,
    VectorStoreUnavailableError,
    VectorStoreWriteError,
)

logger = logging.getLogger(__name__)
ResultT = TypeVar("ResultT")
Sleeper = Callable[[float], None]

ID_COLUMN = "chunk_id"
CONTENT_COLUMN = "content"
EMBEDDING_COLUMN = "embedding"
METADATA_COLUMN_NAMES = [
    "document_id",
    "filename",
    "document_type",
    "document_title",
    "section",
    "page_start",
    "page_end",
    "chunk_index",
    "word_count",
    "embedding_text",
]


class LangChainVectorStore(Protocol):
    """Small portion of PGVectorStore used by the application adapter."""

    def add_embeddings(
        self,
        texts: Sequence[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        ids: list[str],
    ) -> list[str]: ...

    def similarity_search_with_score_by_vector(
        self,
        embedding: list[float],
        k: int | None = None,
        filter: dict | None = None,
    ) -> list[tuple[Document, float]]: ...


class LangChainPostgresVectorStore:
    """Store existing embeddings and typed metadata through LangChain."""

    def __init__(
        self,
        settings: Settings,
        embedding_provider: EmbeddingProvider,
        *,
        vector_store: LangChainVectorStore | None = None,
        sleeper: Sleeper = sleep,
    ) -> None:
        self._table_name = settings.vector_store_table_name
        self._max_retries = settings.vector_store_max_retries
        self._retry_delay_seconds = settings.vector_store_retry_delay_seconds
        self._retrieval_candidate_count = settings.retrieval_candidate_count
        self._sleeper = sleeper
        self._vector_store = vector_store or self._build_vector_store(
            settings,
            embedding_provider,
        )

    def store_chunks(self, chunks: Sequence[EmbeddedChunk]) -> int:
        """Store precomputed vectors and metadata without embedding them again."""

        if not chunks:
            return 0

        document_ids = {chunk.metadata.document_id for chunk in chunks}
        if len(document_ids) != 1:
            raise VectorStoreWriteError(
                "one storage batch must contain chunks from one document"
            )

        ids = [chunk.metadata.chunk_id for chunk in chunks]
        texts = [chunk.text for chunk in chunks]
        embeddings = [list(chunk.embedding) for chunk in chunks]
        metadatas = [self._metadata_for(chunk) for chunk in chunks]

        stored_ids = self._run_with_retry(
            lambda: self._vector_store.add_embeddings(
                texts=texts,
                embeddings=embeddings,
                metadatas=metadatas,
                ids=ids,
            ),
            operation="store chunks",
            operation_error=VectorStoreWriteError,
        )
        if stored_ids != ids:
            raise VectorStoreWriteError(
                "vector store did not persist the expected document chunks"
            )
        return len(stored_ids)

    def retrieve_candidates(self, query: EmbeddedQuery) -> VectorSearchResult:
        """Retrieve a broad, distance-ordered shortlist for later reranking."""

        metadata_filter = self._metadata_filter(query)
        logger.info(
            "Vector retrieval started: candidate_limit=%s, filter_fields=%s",
            self._retrieval_candidate_count,
            sorted(query.scope.as_metadata_filter()),
        )
        try:
            documents_with_distances = self._run_with_retry(
                lambda: self._vector_store.similarity_search_with_score_by_vector(
                    embedding=list(query.embedding),
                    k=self._retrieval_candidate_count,
                    filter=metadata_filter,
                ),
                operation="retrieve candidates",
                operation_error=VectorStoreRetrievalError,
            )
            candidates = tuple(
                sorted(
                    (
                        self._retrieved_chunk(document, distance)
                        for document, distance in documents_with_distances
                    ),
                    key=lambda candidate: candidate.vector_distance,
                )[: self._retrieval_candidate_count]
            )
        except VectorStoreOperationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise VectorStoreRetrievalError(
                "vector store returned invalid candidate data"
            ) from exc

        logger.info(
            "Vector retrieval completed: candidates=%s",
            len(candidates),
        )
        return VectorSearchResult(query=query, candidates=candidates)

    def _build_vector_store(
        self,
        settings: Settings,
        embedding_provider: EmbeddingProvider,
    ) -> PGVectorStore:
        if settings.database_url is None:
            raise VectorStoreConfigurationError(
                "DOC_INTEL_DATABASE_URL is not configured"
            )

        database_url = make_url(settings.database_url).set(
            drivername="postgresql+asyncpg"
        )
        engine = PGEngine.from_connection_string(
            database_url,
            pool_pre_ping=True,
            pool_timeout=settings.vector_store_connect_timeout_seconds,
            connect_args={
                "timeout": settings.vector_store_connect_timeout_seconds,
                "command_timeout": (settings.vector_store_statement_timeout_ms / 1_000),
            },
        )

        try:
            return self._create_vector_store(engine, embedding_provider)
        except ValueError as exc:
            if "does not exist" not in str(exc):
                raise VectorStoreConfigurationError(
                    "pgvector table has an incompatible schema"
                ) from exc

        engine.init_vectorstore_table(
            table_name=self._table_name,
            vector_size=settings.embedding_dimensions,
            content_column=CONTENT_COLUMN,
            embedding_column=EMBEDDING_COLUMN,
            metadata_columns=self._metadata_columns(),
            id_column=Column(ID_COLUMN, "TEXT", nullable=False),
            store_metadata=False,
        )
        return self._create_vector_store(engine, embedding_provider)

    def _create_vector_store(
        self,
        engine: PGEngine,
        embedding_provider: EmbeddingProvider,
    ) -> PGVectorStore:
        return PGVectorStore.create_sync(
            engine=engine,
            embedding_service=cast(Embeddings, embedding_provider),
            table_name=self._table_name,
            content_column=CONTENT_COLUMN,
            embedding_column=EMBEDDING_COLUMN,
            metadata_columns=METADATA_COLUMN_NAMES,
            id_column=ID_COLUMN,
        )

    def _metadata_columns(self) -> list[Column]:
        return [
            Column("document_id", "UUID", nullable=False),
            Column("filename", "TEXT", nullable=False),
            Column("document_type", "TEXT", nullable=False),
            Column("document_title", "TEXT", nullable=False),
            Column("section", "TEXT", nullable=False),
            Column("page_start", "INTEGER", nullable=False),
            Column("page_end", "INTEGER", nullable=False),
            Column("chunk_index", "INTEGER", nullable=False),
            Column("word_count", "INTEGER", nullable=False),
            Column("embedding_text", "TEXT", nullable=False),
        ]

    def _metadata_for(self, chunk: EmbeddedChunk) -> dict:
        metadata = chunk.metadata
        return {
            "document_id": metadata.document_id,
            "filename": metadata.filename,
            "document_type": metadata.document_type.value,
            "document_title": metadata.document_title,
            "section": metadata.section,
            "page_start": metadata.page_start,
            "page_end": metadata.page_end,
            "chunk_index": metadata.chunk_index,
            "word_count": metadata.word_count,
            "embedding_text": chunk.embedding_text,
        }

    @staticmethod
    def _metadata_filter(query: EmbeddedQuery) -> dict | None:
        metadata_filter: dict[str, object] = dict(
            query.scope.as_metadata_filter()
        )
        if query.scope.filename is not None:
            escaped_filename = (
                query.scope.filename.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            metadata_filter["filename"] = {"$ilike": escaped_filename}
        return metadata_filter or None

    @staticmethod
    def _retrieved_chunk(document: Document, distance: float) -> RetrievedChunk:
        metadata = document.metadata
        chunk_metadata = ChunkMetadata(
            chunk_id=document.id or "",
            document_id=metadata["document_id"],
            filename=metadata["filename"],
            document_type=metadata["document_type"],
            document_title=metadata["document_title"],
            section=metadata["section"],
            page_start=metadata["page_start"],
            page_end=metadata["page_end"],
            chunk_index=metadata["chunk_index"],
            word_count=metadata["word_count"],
        )
        return RetrievedChunk(
            text=document.page_content,
            embedding_text=metadata["embedding_text"],
            metadata=chunk_metadata,
            vector_distance=distance,
        )

    def _run_with_retry(
        self,
        action: Callable[[], ResultT],
        *,
        operation: str,
        operation_error: type[VectorStoreOperationError],
    ) -> ResultT:
        for attempt in range(self._max_retries + 1):
            try:
                return action()
            except VectorStoreOperationError:
                raise
            except (
                OperationalError,
                asyncpg.PostgresConnectionError,
                ConnectionError,
                TimeoutError,
                OSError,
            ) as exc:
                if attempt >= self._max_retries:
                    logger.exception(
                        "Vector store unavailable: operation=%s, attempts=%s",
                        operation,
                        attempt + 1,
                    )
                    raise VectorStoreUnavailableError(
                        f"vector store could not {operation}"
                    ) from exc

                delay = self._retry_delay_seconds * (2**attempt)
                logger.warning(
                    "Retrying vector store operation: operation=%s, "
                    "attempt=%s, delay_seconds=%s",
                    operation,
                    attempt + 1,
                    delay,
                )
                self._sleeper(delay)
            except (SQLAlchemyError, asyncpg.PostgresError) as exc:
                logger.exception(
                    "Vector store operation failed: operation=%s",
                    operation,
                )
                raise operation_error(
                    f"vector store could not {operation}"
                ) from exc

        raise AssertionError("unreachable vector-store retry state")
