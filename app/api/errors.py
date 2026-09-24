"""HTTP status for every error code the API can return."""

from types import MappingProxyType

REQUEST_INVALID = "request.invalid"
HTTP_NOT_FOUND = "http.not_found"
HTTP_METHOD_NOT_ALLOWED = "http.method_not_allowed"

FRAMEWORK_CODES = frozenset(
    {REQUEST_INVALID, HTTP_NOT_FOUND, HTTP_METHOD_NOT_ALLOWED}
)

ERROR_STATUS = MappingProxyType(
    {
        "upload.not_pdf": 415,
        "upload.empty": 422,
        "upload.too_large": 413,
        "request.invalid_names_json": 422,
        REQUEST_INVALID: 422,
        "ocr.unreadable": 422,
        "ocr.engine_failure": 500,
        "ner.failure": 500,
        "embedding.failure": 500,
        "vector_store.unavailable": 503,
        "vector_store.timeout": 504,
        "llm.unavailable": 502,
        "llm.timeout": 504,
        "llm.not_configured": 503,
        "job.not_found": 404,
        "blob_store.unavailable": 503,
        "job_store.unavailable": 503,
        "job_queue.unavailable": 503,
        HTTP_NOT_FOUND: 404,
        HTTP_METHOD_NOT_ALLOWED: 405,
        "internal.unexpected": 500,
    }
)
