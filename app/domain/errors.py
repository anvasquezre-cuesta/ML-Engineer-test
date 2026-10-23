"""Domain errors.

Services raise these; one set of exception handlers maps them to HTTP status
codes, so services never import FastAPI.
"""


class DomainError(Exception):
    """Base class for errors the API reports to the client."""


class UnsupportedMediaType(DomainError):
    """The upload is not a PDF (checked by content, not extension)."""


class InvalidDocument(DomainError):
    """The upload is empty, corrupt or encrypted, or ``names`` is malformed."""


class DocumentTooLarge(DomainError):
    """The upload exceeds the byte or page limit."""


class UpstreamUnavailable(DomainError):
    """A dependency (LLM, vector store) failed after its timeout and retries."""
