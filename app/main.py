"""FastAPI application entrypoint.

Assemble the app here: mount the routers under ``/api``, add ``GET /health``,
and wire whatever cross-cutting concerns you decide on (config, logging,
error handling, lifecycle). This skeleton just registers the routers.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.extract import router as extract_router
from app.core.config import get_settings
from app.api.rag import router as rag_router
from app.core.errors import register_exception_handlers
from app.core.logging_setup import setup_logging
from app.dependencies import lifespan

setup_logging()

app = FastAPI(title="Document Intelligence Service", lifespan=lifespan)

register_exception_handlers(app)
app.include_router(extract_router, prefix="/api", tags=["extraction"])
app.include_router(rag_router, prefix="/api", tags=["rag"])

settings = get_settings()
app.mount("/viewer", StaticFiles(directory=settings.static_dir, check_dir=False), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}
