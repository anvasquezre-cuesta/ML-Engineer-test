"""Authenticated access to the optional, single latest extraction preview."""

import json
import time

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response


router = APIRouter()
NO_CACHE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}


def _authorized_store(request: Request):
    store = getattr(request.app.state, "extraction_preview_store", None)
    if store is None:
        raise HTTPException(404, "Preview unavailable", headers=NO_CACHE)
    if not store.authorized(request.headers.get("authorization")):
        raise HTTPException(401, "Preview authentication required", headers={"WWW-Authenticate": "Bearer", **NO_CACHE})
    return store


@router.get("/extract/preview", include_in_schema=False)
async def latest_preview(request: Request):
    preview = _authorized_store(request).get()
    if preview is None:
        raise HTTPException(404, "Preview unavailable", headers=NO_CACHE)
    body = {"preview_id": preview.preview_id, "stages": list(preview.stages),
            "expires_in_seconds": max(0, int(preview.expires_at - time.monotonic()))}
    return Response(json.dumps(body), media_type="application/json", headers=NO_CACHE)


@router.get("/extract/preview/{preview_id}/document", include_in_schema=False)
async def preview_document(preview_id: str, request: Request):
    preview = _authorized_store(request).get(preview_id)
    if preview is None:
        raise HTTPException(404, "Preview unavailable", headers=NO_CACHE)
    return Response(preview.pdf, media_type="application/pdf", headers={
        **NO_CACHE, "Content-Disposition": 'attachment; filename="extraction-preview.pdf"',
    })


@router.get("/extract/preview/{preview_id}/stages/{stage}", include_in_schema=False)
async def preview_stage(preview_id: str, stage: str, request: Request):
    preview = _authorized_store(request).get(preview_id)
    if preview is None or stage not in preview.stages:
        raise HTTPException(404, "Preview unavailable", headers=NO_CACHE)
    return Response(preview.stages[stage], media_type="application/json", headers=NO_CACHE)
