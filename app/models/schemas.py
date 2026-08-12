"""API request/response contract.

These schemas are the FIXED contract for the service — the graders send and
assert against exactly these shapes. You may add optional fields if you have a
reason (document it in DECISIONS.md), but do not remove or rename anything here.
"""

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """A name's location on a page, in PDF coordinate space (points, 72/inch)."""

    page_number: int = Field(ge=0, description="0-based page index")
    x: float
    y: float
    width: float
    height: float


class ExtractedName(BaseModel):
    name: str
    bounding_box: BoundingBox


class FuzzyMatch(BaseModel):
    extracted_name: str
    matched_name: str
    score: float = Field(ge=0.0, le=1.0, description="0..1 similarity")


class NamePair(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)


class ExtractionResponse(BaseModel):
    extracted_names: list[ExtractedName]
    fuzzy_matches: list[FuzzyMatch] = []


class IngestResponse(BaseModel):
    status: str
    chunks_stored: int


class RAGRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class RAGResponse(BaseModel):
    answer: str
    sources: list[str] = []


class HealthResponse(BaseModel):
    status: str
