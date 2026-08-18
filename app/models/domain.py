"""Internal models shared by the document-extraction services.

Unlike :mod:`app.models.schemas`, these models are not part of the HTTP API
contract.  They preserve the OCR and NER metadata needed to locate a detected
person on a PDF page.
"""

from dataclasses import dataclass

from app.models.schemas import BoundingBox


@dataclass(frozen=True, slots=True)
class OCRWord:
    """A word recognized by OCR.

    ``start`` and ``end`` are offsets into the containing ``OCRPage.text``;
    ``end`` is exclusive. Confidence is normalized to the application's 0-to-1
    scale. The bounding box is already converted to PDF points.
    """

    text: str
    bounding_box: BoundingBox
    confidence: float
    start: int
    end: int
    block_number: int
    paragraph_number: int
    line_number: int
    word_number: int

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("OCR word text cannot be empty")
        if not 0 <= self.confidence <= 1:
            raise ValueError("OCR confidence must be between 0 and 1")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("OCR word offsets must define a non-empty span")

        position_values = (
            self.block_number,
            self.paragraph_number,
            self.line_number,
            self.word_number,
        )
        if any(value < 0 for value in position_values):
            raise ValueError("OCR position identifiers cannot be negative")


@dataclass(frozen=True, slots=True)
class OCRPage:
    """OCR text and word metadata for one zero-based PDF page."""

    page_number: int
    text: str
    words: tuple[OCRWord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "words", tuple(self.words))

        if self.page_number < 0:
            raise ValueError("Page number cannot be negative")

        for word in self.words:
            if word.bounding_box.page_number != self.page_number:
                raise ValueError("OCR word and containing page numbers must match")
            if word.end > len(self.text):
                raise ValueError("OCR word offsets must fall within the page text")


@dataclass(frozen=True, slots=True)
class OCRDocument:
    """The complete OCR result, with one entry for every PDF page."""

    pages: tuple[OCRPage, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "pages", tuple(self.pages))

        if not self.pages:
            raise ValueError("OCR document must contain at least one page")

        page_numbers = tuple(page.page_number for page in self.pages)
        expected_page_numbers = tuple(range(len(self.pages)))
        if page_numbers != expected_page_numbers:
            raise ValueError("OCR document pages must be ordered and zero-based")


@dataclass(frozen=True, slots=True)
class PersonMention:
    """A PERSON entity found within one OCR page.

    The page-relative offsets connect the NER result back to the OCR words used
    to calculate the final bounding box.
    """

    name: str
    page_number: int
    start: int
    end: int

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Person name cannot be empty")
        if self.page_number < 0:
            raise ValueError("Page number cannot be negative")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Person mention offsets must define a non-empty span")
