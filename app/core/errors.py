class AppError(Exception):
    """Domain error with the HTTP status the router should map it to."""

    status_code = 500

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class InvalidUpload(AppError):
    status_code = 400


class PdfError(AppError):
    status_code = 422


class VectorStoreError(AppError):
    status_code = 503


class LLMError(AppError):
    status_code = 503
