FROM python:3.12-slim

# tesseract + the language packs OCR_LANGUAGES may reference
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 svc

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

# dependencies first so code changes don't invalidate this layer
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

COPY --chown=svc:svc app ./app
COPY --chown=svc:svc static ./static
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

# bake the embedding model into the image so the container never needs internet at runtime
ARG EMBEDDING_MODEL=all-MiniLM-L6-v2
ENV HF_HOME=/app/.hf
RUN .venv/bin/python -c "from sentence_transformers import SentenceTransformer as S; S('${EMBEDDING_MODEL}')"

# the venv and model cache stay root-owned and read-only; only the data dir is writable
RUN mkdir -p /app/chroma_data && chown svc:svc /app/chroma_data
USER svc

ENV PATH="/app/.venv/bin:$PATH" CHROMA_DIR=/app/chroma_data HF_HUB_OFFLINE=1
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD curl -fs http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
