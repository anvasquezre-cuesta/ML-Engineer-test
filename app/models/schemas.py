"""API request/response contract.

These schemas are the FIXED contract for the service — the graders send and
assert against exactly these shapes. You may add optional fields if you have a
reason (document it in DECISIONS.md), but do not remove or rename anything here.
"""

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """A name's location on a page, in PDF coordinate space (points, 72/inch).

    Origin at the page's top-left corner, y growing downward (PyMuPDF / pdf.js
    convention). In native PDF space (bottom-left origin) the box's lower edge is
    ``page_height - y - height``.
    """

    page_number: int = Field(ge=0, description="0-based page index")
    x: float = Field(description="Left edge, points from the page's left side")
    y: float = Field(description="Top edge, points from the page's top (y grows downward)")
    width: float = Field(description="Width in points")
    height: float = Field(description="Height in points")


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


# Added (not part of the original contract): GET /health/ready. /health is kept exactly as
# specified for liveness; readiness reports each dependency separately. See DECISIONS.md.
class CheckStatus(BaseModel):
    ok: bool
    critical: bool
    detail: str
    duration_ms: float


class ReadinessResponse(BaseModel):
    status: str = Field(description='"ready", "degraded" (non-critical failure) or "unavailable"')
    checks: dict[str, CheckStatus]
