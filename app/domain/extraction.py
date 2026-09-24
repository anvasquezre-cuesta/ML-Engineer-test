"""Value objects of the name extraction pipeline.

Coordinates are PDF points (72 per inch) with the origin at the top-left
corner of the page and y growing downwards. Page numbers are 0-based.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Box:
    """Axis-aligned rectangle on a page, in points.

    Attributes:
        x: Left edge.
        y: Top edge.
        width: Horizontal extent.
        height: Vertical extent.
    """

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class PageImage:
    """A rendered page as 8-bit grayscale pixels.

    Attributes:
        page_number: 0-based page index.
        pixels: Row-major grayscale bytes, one byte per pixel.
        width_px: Image width in pixels.
        height_px: Image height in pixels.
        width_pt: Page width in points.
        height_pt: Page height in points.
    """

    page_number: int
    pixels: bytes
    width_px: int
    height_px: int
    width_pt: float
    height_pt: float


@dataclass(frozen=True, slots=True)
class OcrWord:
    """A word recognized on a page.

    Attributes:
        text: Recognized characters.
        box: Location of the word in points.
        block: Index of the text block the word belongs to.
        line: Index of the line within its block.
        confidence: Recognition confidence in 0..100.
    """

    text: str
    box: Box
    block: int
    line: int
    confidence: float


@dataclass(frozen=True, slots=True)
class PageWords:
    """Every word recognized on one page, in reading order.

    Attributes:
        page_number: 0-based page index.
        words: Recognized words.
    """

    page_number: int
    words: tuple[OcrWord, ...]


@dataclass(frozen=True, slots=True)
class TextWord:
    """An OCR word located inside the text of its page.

    Attributes:
        word: The recognized word.
        start: Offset of the word's first character in the page text.
        end: Offset one past the word's last character.
    """

    word: OcrWord
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class PageText:
    r"""The text of a page, with every word's position in it.

    Words on a line are separated by a space, lines by ``\n`` and blocks by
    ``\n\n``, so NER sees the page layout.

    Attributes:
        page_number: 0-based page index.
        text: The page text.
        words: The words in reading order, with their offsets in ``text``.
    """

    page_number: int
    text: str
    words: tuple[TextWord, ...]


@dataclass(frozen=True, slots=True)
class EntitySpan:
    """A PERSON entity found in a text, as character offsets.

    Attributes:
        start: Offset of the first character.
        end: Offset one past the last character.
        text: The entity text, equal to ``source[start:end]``.
    """

    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class NameOccurrence:
    """One occurrence of a person's name on a page.

    Attributes:
        name: The name as it appears, without titles.
        page_number: 0-based page index.
        box: Location of this occurrence in points.
    """

    name: str
    page_number: int
    box: Box


@dataclass(frozen=True, slots=True)
class QueryName:
    """A person name the caller wants to match against the document.

    Attributes:
        first_name: Given name.
        last_name: Family name.
    """

    first_name: str
    last_name: str

    @property
    def full_name(self) -> str:
        """Returns the name as ``first_name last_name``.

        Returns:
            The full name.
        """
        return f"{self.first_name} {self.last_name}"


@dataclass(frozen=True, slots=True)
class NameMatch:
    """An extracted name that matches a queried name.

    Attributes:
        extracted_name: Name found in the document.
        matched_name: Full queried name it matched.
        score: Similarity in 0..1.
    """

    extracted_name: str
    matched_name: str
    score: float
