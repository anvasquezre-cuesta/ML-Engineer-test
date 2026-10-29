# syntax=docker/dockerfile:1
# Document Intelligence Service — one container: API + Tesseract + embedded Chroma.
# Models are baked in at build time so the container starts offline and fast.

FROM ghcr.io/astral-sh/uv:0.11.7 AS uv

FROM python:3.12-slim

# Tesseract binary + English and Spanish language data (OCR languages come from config).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    HF_HOME=/opt/hf \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first (cached layer), then the models, then the code, so a code change
# rebuilds only the last layers. The lock pins CPU-only torch; uv's download cache is a
# build-time mount, so it never lands in the image.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

# Bake the embedder and reranker into the image (must match the configured defaults).
ARG EMBEDDING_MODEL=intfloat/multilingual-e5-small
ARG RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
RUN python -c "from sentence_transformers import CrossEncoder, SentenceTransformer; \
SentenceTransformer('${EMBEDDING_MODEL}'); CrossEncoder('${RERANKER_MODEL}')"

COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# Non-root user; it only writes to /data (the vector store volume) and /tmp.
RUN useradd --uid 10001 --no-create-home app \
    && mkdir -p /data \
    && chown app:app /data
USER app

ENV HF_HUB_OFFLINE=1 \
    DOCINTEL_VECTOR_STORE_PATH=/data/chroma

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
