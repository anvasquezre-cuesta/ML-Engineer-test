FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Fail the build if the locked English model is absent or incompatible.
RUN python -c "import spacy; assert 'ner' in spacy.load('en_core_web_sm').pipe_names"

# The embedding revision is pinned and checked; runtime loading is local only.
COPY app/core/embedding_model.py /tmp/embedding_model.py
RUN HF_HUB_DISABLE_XET=1 python /tmp/embedding_model.py /opt/models/all-minilm-l6-v2

COPY app ./app
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/ingestion \
    && chown appuser:appuser /app/data /app/data/ingestion \
    && chmod 700 /app/data/ingestion
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
