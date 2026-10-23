"""``GET /viewer``: the audit viewer, a single static page that calls ``/api/extract``.

It renders the uploaded PDF with pdf.js and draws each returned box over the
page, so a compliance reviewer can confirm a name is where the API says it is.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

VIEWER_HTML = Path(__file__).parents[1] / "static" / "viewer.html"

router = APIRouter()


@router.get("/viewer", include_in_schema=False)
def viewer() -> FileResponse:
    return FileResponse(VIEWER_HTML, media_type="text/html")
