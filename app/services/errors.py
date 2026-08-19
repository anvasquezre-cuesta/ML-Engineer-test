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
