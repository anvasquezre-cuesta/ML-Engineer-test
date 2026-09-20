"""
Module: app.main
Path: app/main.py
Description: FastAPI application entry point and router registration.
"""

from fastapi import FastAPI

from app.api.extract import router as extract_router
from app.api.rag import router as rag_router

app = FastAPI(title="Document Intelligence Service")

app.include_router(extract_router, prefix="/api", tags=["extraction"])
app.include_router(rag_router, prefix="/api", tags=["rag"])


@app.get("/health")
def health() -> dict[str, str]:
    """Return the service health status."""

    return {"status": "ok"}
