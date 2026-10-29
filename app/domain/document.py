"""What OCR knows about a document: pages, their words and where each word is."""

from dataclasses import dataclass

from app.domain.geometry import BoundingBox

LineKey = tuple[int, int, int]
"""Identifies a text line within a page: (block, paragraph, line)."""


@dataclass(frozen=True, slots=True)
class Word:
    """One recognized word, its box in PDF points and OCR confidence (0..100)."""

    text: str
    box: BoundingBox
    confidence: float
    line_key: LineKey

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("word text must be non-empty")
        if not 0.0 <= self.confidence <= 100.0:
            raise ValueError(f"confidence must be within [0, 100], got {self.confidence}")


@dataclass(frozen=True, slots=True)
class Page:
    """A page (0-based ``index``) in points, with its words in reading order."""

    index: int
    width: float
    height: float
    words: tuple[Word, ...]

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError(f"page index must be >= 0, got {self.index}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("page size must be positive")


@dataclass(frozen=True, slots=True)
class PageImage:
    """A rendered page: PNG bytes at ``dpi`` plus the page size in points."""

    index: int
    width_pt: float
    height_pt: float
    dpi: int
    png: bytes

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError(f"page index must be >= 0, got {self.index}")
        if self.dpi <= 0:
            raise ValueError(f"dpi must be positive, got {self.dpi}")


@dataclass(frozen=True, slots=True)
class PdfInfo:
    """What can be known about a PDF without rendering it."""

    page_count: int
    encrypted: bool
