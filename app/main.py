"""
Module: app.main
Path: app/main.py
Description: FastAPI application entry point, router registration, and API error handling.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api.extract import router as extract_router
from app.api.rag import router as rag_router
from app.services.llm_provider import LLMProviderError
from app.services.vector_service import VectorStoreError

app = FastAPI(title="Document Intelligence Service")

app.include_router(
    extract_router,
    prefix="/api",
    tags=["extraction"],
)

app.include_router(
    rag_router,
    prefix="/api",
    tags=["rag"],
)


@app.exception_handler(VectorStoreError)
def handle_vector_store_error(
    request: Request,
    exc: VectorStoreError,
) -> JSONResponse:
    """Return a safe response when the vector store cannot complete an operation."""
    return JSONResponse(
        status_code=503,
        content={
            "detail": "The document retrieval service is temporarily unavailable."
        },
    )


@app.exception_handler(LLMProviderError)
def handle_llm_provider_error(
    request: Request,
    exc: LLMProviderError,
) -> JSONResponse:
    """Return a safe response when the configured LLM cannot generate a response."""
    return JSONResponse(
        status_code=502,
        content={"detail": "The language model service is temporarily unavailable."},
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Return the basic application health status."""
    return {"status": "ok"}


@app.get("/audit", response_class=FileResponse)
def audit_viewer() -> FileResponse:
    """Serve the browser-based document extraction audit viewer."""
    viewer_path = Path(__file__).parent / "static" / "audit_viewer.html"
    return FileResponse(viewer_path)
