"""Internal OCR results, independent of the public HTTP response schemas."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WordBox:
    """Rectangle in unrotated, crop-relative PDF points, with a top-left origin."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class OCRWord:
    text: str
    box: WordBox
    # Offsets address the text of this word's page, not the whole document.
    char_start: int
    char_end: int
    block_number: int
    paragraph_number: int
    line_number: int
    confidence: float


@dataclass(frozen=True)
class OCRPage:
    page_number: int
    width: float
    height: float
    text: str
    words: tuple[OCRWord, ...]


@dataclass(frozen=True)
class OCRDocument:
    pages: tuple[OCRPage, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages)
