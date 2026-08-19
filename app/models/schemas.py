"""API request/response contract.

These schemas are the FIXED contract for the service — the graders send and
assert against exactly these shapes. You may add optional fields if you have a
reason (document it in DECISIONS.md), but do not remove or rename anything here.
"""

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """A name's location on a page, in PDF coordinate space (points, 72/inch)."""

    page_number: int = Field(ge=0, description="0-based page index")
    x: float = Field(description="Left edge in PDF points")
    y: float = Field(description="Top edge in PDF points")
    width: float = Field(description="Box width in PDF points")
    height: float = Field(description="Box height in PDF points")


class ExtractedName(BaseModel):
    name: str = Field(description="Person name detected by NER")
    bounding_box: BoundingBox = Field(
        description="Location of this name occurrence in the PDF"
    )


class FuzzyMatch(BaseModel):
    extracted_name: str = Field(description="Name detected in the PDF")
    matched_name: str = Field(description="Best matching submitted full name")
    score: float = Field(ge=0.0, le=1.0, description="0..1 similarity")


class NamePair(BaseModel):
    first_name: str = Field(min_length=1, description="Person's given name")
    last_name: str = Field(min_length=1, description="Person's family name")


class ExtractionResponse(BaseModel):
    extracted_names: list[ExtractedName] = Field(
        description="Located PERSON occurrences in document order"
    )
    fuzzy_matches: list[FuzzyMatch] = Field(
        default_factory=list,
        description="Best submitted-name matches meeting the configured threshold",
    )


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
