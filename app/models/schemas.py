"""API request/response contract.

These schemas are the fixed contract for the service: clients send and
assert against exactly these shapes. Optional fields may be added, but nothing
here may be removed or renamed.
"""

from pydantic import BaseModel
from pydantic import Field


class BoundingBox(BaseModel):
    """A name's location on a page, in PDF coordinate space.

    Attributes:
        page_number: 0-based page index.
        x: Left edge in points (72 per inch).
        y: Top edge in points (72 per inch).
        width: Box width in points.
        height: Box height in points.
    """

    page_number: int = Field(ge=0, description="0-based page index")
    x: float
    y: float
    width: float
    height: float


class ExtractedName(BaseModel):
    """A PERSON name found in the document and where it appears.

    Attributes:
        name: The name as recognized in the document.
        bounding_box: Location of this occurrence.
    """

    name: str
    bounding_box: BoundingBox


class FuzzyMatch(BaseModel):
    """An extracted name matched against a queried name.

    Attributes:
        extracted_name: Name found in the document.
        matched_name: Queried name it matched.
        score: Similarity in 0..1.
    """

    extracted_name: str
    matched_name: str
    score: float = Field(ge=0.0, le=1.0, description="0..1 similarity")


class NamePair(BaseModel):
    """A queried person name.

    Attributes:
        first_name: Given name.
        last_name: Family name.
    """

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)


class ExtractionResponse(BaseModel):
    """Response of ``POST /api/extract``.

    Attributes:
        extracted_names: Every name occurrence with its box.
        fuzzy_matches: Extracted names that match the queried names.
    """

    extracted_names: list[ExtractedName]
    fuzzy_matches: list[FuzzyMatch] = []


class IngestResponse(BaseModel):
    """Response of ``POST /api/ingest``.

    Attributes:
        status: Outcome of the ingestion.
        chunks_stored: Number of chunks stored for the document.
    """

    status: str
    chunks_stored: int


class RAGRequest(BaseModel):
    """Request of ``POST /api/ask``.

    Attributes:
        question: Question about the ingested documents.
    """

    question: str = Field(min_length=1, max_length=2000)


class RAGResponse(BaseModel):
    """Response of ``POST /api/ask``.

    Attributes:
        answer: Answer grounded in the retrieved chunks.
        sources: References to the retrieved chunks used.
    """

    answer: str
    sources: list[str] = []


class HealthResponse(BaseModel):
    """Response of ``GET /health``.

    Attributes:
        status: ``ok`` when the service is up.
    """

    status: str
