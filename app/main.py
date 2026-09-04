import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.extract import router as extract_router
from app.api.rag import router as rag_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, request_id_var
from app.models.schemas import HealthResponse
from app.services.embedding_service import SentenceTransformerEmbedder
from app.services.extraction_service import ExtractionPipeline
from app.services.llm_client import OpenAICompatibleLLM
from app.services.ner_service import SpacyNer
from app.services.ocr_service import TesseractOcr
from app.services.rag_service import RagService
from app.services.vector_service import ChromaStore

log = logging.getLogger(__name__)
VIEWER_DIR = Path(__file__).resolve().parent.parent / "static" / "viewer"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build every heavy object once and hang it off app.state."""
    s = get_settings()
    configure_logging(s.log_level)

    ocr = TesseractOcr(s.ocr_dpi, s.ocr_languages, s.ocr_min_confidence, s.max_pages)
    llm = OpenAICompatibleLLM(
        s.llm_base_url,
        s.llm_api_key,
        s.llm_model,
        s.llm_timeout_s,
        s.llm_max_attempts,
        s.llm_extra_body,
    )
    app.state.extraction = ExtractionPipeline(
        ocr, SpacyNer(s.ner_model), s.fuzzy_threshold, s.bbox_token_threshold, s.min_name_tokens
    )
    app.state.rag = RagService(
        ocr,
        SentenceTransformerEmbedder(s.embedding_model),
        ChromaStore(s.chroma_dir, s.chroma_collection),
        llm,
        s.chunk_size,
        s.chunk_overlap,
        s.top_k,
    )
    log.info("startup complete", extra={"ner_model": s.ner_model, "embedding": s.embedding_model})
    yield
    await llm.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="Document Intelligence Service", lifespan=lifespan)
    app.include_router(extract_router, prefix="/api", tags=["extraction"])
    app.include_router(rag_router, prefix="/api", tags=["rag"])
    if VIEWER_DIR.exists():
        app.mount("/viewer", StaticFiles(directory=VIEWER_DIR, html=True), name="viewer")

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse(
            {"detail": "internal error", "request_id": request_id_var.get()}, status_code=500
        )

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request_id_var.set(request_id)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return response

    return app


app = create_app()
