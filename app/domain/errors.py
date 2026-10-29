"""Error hierarchy, named by the violated rule (CONSTITUTION §8, §10).

Every error carries a stable machine ``code``; the API layer maps codes to HTTP status.
Messages never contain person names or document text (CONSTITUTION §9).
"""


class DomainError(Exception):
    """A business rule or input constraint was violated (client-side problem)."""

    code = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InfrastructureError(Exception):
    """An adapter or external dependency failed (server-side problem)."""

    code = "infrastructure_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UploadMissing(DomainError):
    """The request carries no PDF file field."""

    code = "pdf_file_missing"


class UploadEmpty(DomainError):
    """The uploaded file has zero bytes."""

    code = "upload_empty"


class UploadTooLarge(DomainError):
    """The uploaded file exceeds the configured size limit."""

    code = "upload_too_large"


class UploadIsNotPdf(DomainError):
    """The uploaded bytes do not start with the PDF signature."""

    code = "upload_not_pdf"


class PdfEncrypted(DomainError):
    """The PDF is password-protected and cannot be rendered."""

    code = "pdf_encrypted"


class PdfUnreadable(DomainError):
    """The PDF cannot be parsed."""

    code = "pdf_unreadable"


class PdfTooManyPages(DomainError):
    """The PDF has more pages than the configured limit."""

    code = "pdf_too_many_pages"


class NamesInvalid(DomainError):
    """The requested-names list is not a valid list of first/last name pairs."""

    code = "names_invalid"


class OcrUnavailable(InfrastructureError):
    """The OCR engine is missing, crashed or timed out."""

    code = "ocr_unavailable"


class NerModelUnavailable(InfrastructureError):
    """The configured NER model cannot be loaded."""

    code = "ner_model_unavailable"


class EmbeddingModelUnavailable(InfrastructureError):
    """The configured embedding model cannot be loaded."""

    code = "embedding_model_unavailable"


class VectorStoreUnavailable(InfrastructureError):
    """The vector store failed to read or write chunks."""

    code = "vector_store_unavailable"


class RerankerUnavailable(InfrastructureError):
    """The configured reranker model cannot be loaded."""

    code = "reranker_unavailable"


class LlmNotConfigured(InfrastructureError):
    """No API key is configured for the LLM, so answers cannot be generated."""

    code = "llm_not_configured"


class LlmTimeout(InfrastructureError):
    """The LLM did not answer within the configured timeout (after retries)."""

    code = "llm_timeout"


class LlmRateLimited(InfrastructureError):
    """The LLM provider kept rejecting calls for exceeding its rate limit."""

    code = "llm_rate_limited"


class LlmUnavailable(InfrastructureError):
    """The LLM provider failed (server error, connection error, rejected key)."""

    code = "llm_unavailable"
