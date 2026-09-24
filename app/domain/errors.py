"""Domain errors with stable codes shared by the API, the worker and logs.

Each concrete error declares a dotted ``code`` that never changes once
published, whether the condition is ``retryable`` (transient) and a constant
``title``. HTTP statuses are assigned by the API layer, not here.
"""

from typing import ClassVar


class AppError(Exception):
    """Base class for every error the service reports to its callers.

    Attributes:
        code: Stable, low-cardinality identifier, e.g. ``vector_store.timeout``.
        retryable: Whether retrying the same work may succeed.
        title: Constant human-readable summary of the error kind.
        detail: Message for this occurrence; never contains names, OCR text
            or filenames.
    """

    code: ClassVar[str]
    retryable: ClassVar[bool]
    title: ClassVar[str]

    def __init__(self, detail: str | None = None) -> None:
        """Initializes the error.

        Args:
            detail: Message for this occurrence. Defaults to ``title``.
        """
        self.detail = detail or self.title
        super().__init__(self.detail)


class UploadNotPdfError(AppError):
    """The uploaded file does not start with the PDF magic bytes."""

    code = "upload.not_pdf"
    retryable = False
    title = "The uploaded file is not a PDF."


class UploadEmptyError(AppError):
    """The uploaded file has no content."""

    code = "upload.empty"
    retryable = False
    title = "The uploaded file is empty."


class UploadTooLargeError(AppError):
    """The uploaded file exceeds the configured size limit.

    Attributes:
        size_bytes: Size of the rejected upload.
        limit_bytes: Maximum size allowed.
    """

    code = "upload.too_large"
    retryable = False
    title = "The uploaded file is too large."

    def __init__(self, size_bytes: int, limit_bytes: int) -> None:
        """Initializes the error.

        Args:
            size_bytes: Size of the rejected upload.
            limit_bytes: Maximum size allowed.
        """
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"Upload is {size_bytes} bytes; the limit is {limit_bytes} bytes."
        )


class InvalidNamesJsonError(AppError):
    """The ``names`` form field is not a JSON list of first and last names."""

    code = "request.invalid_names_json"
    retryable = False
    title = "The names field is not a valid JSON list of names."


class OcrUnreadableError(AppError):
    """A page cannot be rendered or read, so retrying will not help."""

    code = "ocr.unreadable"
    retryable = False
    title = "A page of the document could not be read."


class OcrEngineError(AppError):
    """The OCR engine crashed, was killed or timed out."""

    code = "ocr.engine_failure"
    retryable = True
    title = "The OCR engine failed."


class NerError(AppError):
    """The named-entity recognition pipeline failed."""

    code = "ner.failure"
    retryable = False
    title = "Named-entity recognition failed."


class EmbeddingError(AppError):
    """The embedding model failed to embed the text."""

    code = "embedding.failure"
    retryable = False
    title = "Embedding the text failed."


class VectorStoreUnavailableError(AppError):
    """The vector store refused the connection or returned a server error."""

    code = "vector_store.unavailable"
    retryable = True
    title = "The vector store is unavailable."


class VectorStoreTimeoutError(AppError):
    """The vector store did not answer in time after adapter retries."""

    code = "vector_store.timeout"
    retryable = True
    title = "The vector store timed out."


class LlmUnavailableError(AppError):
    """The LLM provider returned an error or a server error."""

    code = "llm.unavailable"
    retryable = True
    title = "The language model is unavailable."


class LlmTimeoutError(AppError):
    """The LLM provider did not answer in time after adapter retries."""

    code = "llm.timeout"
    retryable = True
    title = "The language model timed out."


class LlmNotConfiguredError(AppError):
    """No LLM provider, model or credentials are configured."""

    code = "llm.not_configured"
    retryable = False
    title = "The language model is not configured."


class OccurrenceStoreUnavailableError(AppError):
    """The occurrence store failed or timed out after adapter retries."""

    code = "occurrence_store.unavailable"
    retryable = True
    title = "The occurrence store is unavailable."


class OccurrenceIntegrityError(AppError):
    """A sealed generation returned a different number of occurrences."""

    code = "occurrence_store.integrity"
    retryable = False
    title = "A stored document version is incomplete."


class JobNotFoundError(AppError):
    """No job exists with the requested id.

    Attributes:
        job_id: The id that was looked up.
    """

    code = "job.not_found"
    retryable = False
    title = "The job does not exist."

    def __init__(self, job_id: str) -> None:
        """Initializes the error.

        Args:
            job_id: The id that was looked up.
        """
        self.job_id = job_id
        super().__init__(f"Job {job_id} does not exist.")


class DocumentNotFoundError(AppError):
    """No chunks are stored for the requested document.

    Attributes:
        document_key: The key that was looked up.
    """

    code = "document.not_found"
    retryable = False
    title = "The document is not indexed."

    def __init__(self, document_key: str) -> None:
        """Initializes the error.

        Args:
            document_key: The key that was looked up.
        """
        self.document_key = document_key
        super().__init__("No chunks are stored for this document.")


class BlobStoreUnavailableError(AppError):
    """The blob store failed to read or write an object."""

    code = "blob_store.unavailable"
    retryable = True
    title = "The blob store is unavailable."


class JobStoreUnavailableError(AppError):
    """The job store failed to read or write a job."""

    code = "job_store.unavailable"
    retryable = True
    title = "The job store is unavailable."


class JobQueueUnavailableError(AppError):
    """The job queue failed to publish or deliver a message."""

    code = "job_queue.unavailable"
    retryable = True
    title = "The job queue is unavailable."


class UnexpectedError(AppError):
    """An exception that no adapter translated into a domain error."""

    code = "internal.unexpected"
    retryable = False
    title = "An unexpected error occurred."
