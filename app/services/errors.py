"""Errors shared across extraction service implementations."""


class ExtractionServiceError(RuntimeError):
    """Base error for failures inside the extraction pipeline."""


class ExtractionDependencyError(ExtractionServiceError):
    """Raised when an OCR or NER dependency is unavailable."""


class OCRProcessingError(ExtractionDependencyError):
    """Raised when a PDF page cannot be rendered or processed by Tesseract."""


class NERModelLoadError(ExtractionDependencyError):
    """Raised when the configured NER model cannot be loaded."""


class NERProcessingError(ExtractionDependencyError):
    """Raised when person extraction fails for an OCR page."""


class BoundingBoxMappingError(ExtractionServiceError):
    """Raised when OCR and NER page metadata is inconsistent."""


class IngestionServiceError(RuntimeError):
    """Raised when the document-ingestion pipeline cannot continue."""


class DocumentStructureError(IngestionServiceError):
    """Raised when useful structure cannot be recovered from OCR output."""


class DocumentChunkingError(IngestionServiceError):
    """Raised when a structured document cannot produce useful chunks."""


class EmbeddingDependencyError(IngestionServiceError):
    """Raised when the configured embedding provider is unavailable."""


class EmbeddingResponseError(IngestionServiceError):
    """Raised when an embedding provider returns an invalid result."""


class VectorStoreConfigurationError(IngestionServiceError):
    """Raised when vector-store configuration is incomplete or invalid."""


class VectorStoreUnavailableError(IngestionServiceError):
    """Raised when PostgreSQL cannot be reached after configured retries."""


class VectorStoreOperationError(IngestionServiceError):
    """Base error for valid operations rejected by the vector store."""


class VectorStoreWriteError(VectorStoreOperationError):
    """Raised when embedded chunks cannot be persisted safely."""


class VectorStoreRetrievalError(VectorStoreOperationError):
    """Raised when pgvector cannot return a valid candidate shortlist."""


class RerankerServiceError(RuntimeError):
    """Base error for failures in local cross-encoder reranking."""


class RerankerModelLoadError(RerankerServiceError):
    """Raised when the configured local cross-encoder cannot be loaded."""


class RerankerProcessingError(RerankerServiceError):
    """Raised when local cross-encoder inference fails."""


class RerankerResponseError(RerankerServiceError):
    """Raised when the cross-encoder returns incomplete or invalid scores."""


class CandidateSelectionError(RuntimeError):
    """Raised when malformed reranking output cannot be selected safely."""
