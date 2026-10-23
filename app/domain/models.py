"""Domain value objects.

Plain frozen dataclasses: no FastAPI, no library types. Services and adapters
exchange these; routers convert them to the API schemas in ``app.models``.

Coordinate convention: top-left origin, y grows downward (PyMuPDF and pdf.js).
``Box`` carries no unit; each field documents whether it holds pixels or points.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True, slots=True)
class PdfDocument:
    """A validated upload. ``doc_id`` is the SHA-256 of ``data``."""

    doc_id: str
    data: bytes = field(repr=False)
    page_count: int


@dataclass(frozen=True, slots=True)
class PageImage:
    """One rendered page as raw 8-bit RGB pixels, row by row (no padding)."""

    index: int  # 0-based
    width_pt: float
    height_pt: float
    rotation: int  # the page's /Rotate, in degrees
    dpi: int
    width_px: int
    height_px: int
    pixels: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class OcrWord:
    """A recognised word with its box in **pixels** of the page image it came from."""

    text: str
    box_px: Box
    confidence: float  # 0..100
    line_key: tuple[int, int, int]  # Tesseract (block, paragraph, line)


@dataclass(frozen=True, slots=True)
class PageWord:
    """A recognised word with its box in **PDF points** (top-left origin)."""

    text: str
    box: Box
    confidence: float  # 0..100
    line_key: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class OcrPage:
    """Every word on one page, in points, in Tesseract's reading order."""

    index: int  # 0-based
    width_pt: float
    height_pt: float
    words: tuple[PageWord, ...]


@dataclass(frozen=True, slots=True)
class EntitySpan:
    """A person entity as a character range in the text given to the NER model."""

    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class NameMatch:
    extracted: str
    candidate: str
    score: float  # 0..1


@dataclass(frozen=True, slots=True)
class Chunk:
    doc_id: str
    filename: str
    page: int  # 0-based
    chunk_index: int
    text: str

    @property
    def chunk_id(self) -> str:
        return f"{self.doc_id}:{self.page}:{self.chunk_index}"


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk: Chunk
    similarity: float  # 0..1, higher is closer
