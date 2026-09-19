"""
Module: app.models.schemas
Path: app/models/schemas.py
Description: Public API request and response schemas.
"""

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Represent a name location in PDF coordinate space."""

    page_number: int = Field(
        ge=0,
        description="0-based page index",
    )
    x: float
    y: float
    width: float
    height: float


class ExtractedName(BaseModel):
    """Represent an extracted person name and its location."""

    name: str
    bounding_box: BoundingBox


class FuzzyMatch(BaseModel):
    """Represent a fuzzy match between extracted and provided names."""

    extracted_name: str
    matched_name: str
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="0..1 similarity",
    )


class NamePair(BaseModel):
    """Represent a provided first-name and last-name pair."""

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)


class ExtractionResponse(BaseModel):
    """Represent the response from the extraction endpoint."""

    extracted_names: list[ExtractedName]
    fuzzy_matches: list[FuzzyMatch] = []


class IngestResponse(BaseModel):
    """Represent the response from document ingestion."""

    status: str
    chunks_stored: int


class RAGRequest(BaseModel):
    """Represent a question submitted to the RAG endpoint."""

    question: str = Field(
        min_length=1,
        max_length=2000,
    )


class RAGResponse(BaseModel):
    """Represent a grounded RAG answer."""

    answer: str
    sources: list[str] = []


class HealthResponse(BaseModel):
    """Represent the health-check response."""

    status: str
