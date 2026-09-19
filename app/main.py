"""
Module: app.main
Path: app/main.py
Description: FastAPI application entry point.
"""

from fastapi import FastAPI

from app.api.extract import router as extract_router

app = FastAPI(title="Document Intelligence Service")

app.include_router(
    extract_router,
    prefix="/api",
    tags=["extraction"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Return the application health status."""

    return {"status": "ok"}
