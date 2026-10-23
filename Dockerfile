# syntax=docker/dockerfile:1.7
# Document Intelligence Service: CPU-only image with Tesseract, the spaCy model and the
# embedding model baked in, so the container starts without any download.

ARG PYTHON_IMAGE=python:3.12.14-slim-bookworm

# ---------- builder: resolve the locked environment and fetch the embedding model ----------
FROM ${PYTHON_IMAGE} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    HF_HOME=/opt/hf

RUN pip install --no-cache-dir uv==0.12.5

WORKDIR /app
# Dependencies first (cached layer): the lock routes torch to the CPU-only index on Linux.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable

ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN /app/.venv/bin/python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

# ---------- runtime ----------
FROM ${PYTHON_IMAGE} AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/app /app/app
COPY --from=builder --chown=app:app /opt/hf /opt/hf

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    ANONYMIZED_TELEMETRY=False \
    LOG_JSON=true \
    RAG__CHROMA_PATH=/data/chroma \
    RAG__QDRANT_PATH=/data/qdrant

USER app
VOLUME ["/data"]
EXPOSE 8000

# Liveness only (the process answers); compose uses /health/ready for dependency health.
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
