"""
Module: app.models.schemas
Path: app/models/schemas.py
Description: Pydantic schemas for public API requests and responses.
"""

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Represent a name bounding box in PDF coordinate space."""

    page_number: int = Field(ge=0, description="0-based page index")
    x: float
    y: float
    width: float
    height: float


class ExtractedName(BaseModel):
    """Represent an extracted person name and its location."""

    name: str
    bounding_box: BoundingBox


class FuzzyMatch(BaseModel):
    """Represent a fuzzy match against a candidate name."""

    extracted_name: str
    matched_name: str
    score: float = Field(ge=0.0, le=1.0)


class NamePair(BaseModel):
    """Represent a candidate first-name and last-name pair."""

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)


class ExtractionResponse(BaseModel):
    """Represent the document extraction API response."""

    extracted_names: list[ExtractedName]
    fuzzy_matches: list[FuzzyMatch] = Field(default_factory=list)


class IngestResponse(BaseModel):
    """Represent the document ingestion API response."""

    status: str
    chunks_stored: int


class RAGRequest(BaseModel):
    """Represent a question submitted to the RAG endpoint."""

    question: str = Field(min_length=1, max_length=2000)


class RAGResponse(BaseModel):
    """Represent a grounded RAG answer and its sources."""

    answer: str
    sources: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Represent the service health response."""

    status: str
