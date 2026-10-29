"""`GET /viewer` — the audit viewer: one static page that calls the API (TRD §3).

The page renders the PDF with pdf.js and draws the boxes `/api/extract` returns, so a
reviewer can confirm each name is where the API says it is. It also ingests and asks,
to exercise the RAG endpoints. Served from the same origin, so no CORS is needed.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

VIEWER_PAGE = Path(__file__).parent / "viewer.html"

router = APIRouter()


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Send a browser opening the bare host to the viewer."""
    return RedirectResponse("/viewer")


@router.get("/viewer", include_in_schema=False)
def viewer() -> FileResponse:
    """Serve the self-contained viewer page."""
    return FileResponse(VIEWER_PAGE, media_type="text/html")
