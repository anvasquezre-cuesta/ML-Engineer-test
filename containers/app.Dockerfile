FROM python:3.12.14-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    DOCINTEL_EMBEDDINGS__CACHE_DIR=/opt/models/fastembed
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project
COPY pyproject.toml uv.lock ./
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable
COPY scripts/__init__.py scripts/bake_models.py ./scripts/
RUN .venv/bin/python -m scripts.bake_models

FROM python:3.12.14-slim-bookworm AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home docintel
WORKDIR /app
COPY --from=builder --chown=docintel:docintel /app/.venv /app/.venv
COPY --from=builder --chown=docintel:docintel /opt/models /opt/models
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DOCINTEL_EMBEDDINGS__CACHE_DIR=/opt/models/fastembed \
    DOCINTEL_EMBEDDINGS__LOCAL_FILES_ONLY=true
USER docintel
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# AWS Lambda: the same image with the Lambda Web Adapter extension, which
# forwards API Gateway events to uvicorn unchanged.
FROM runtime AS lambda
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0 /lambda-adapter /opt/extensions/lambda-adapter
ENV AWS_LWA_PORT=8000 \
    AWS_LWA_READINESS_CHECK_PATH=/health \
    AWS_LWA_ASYNC_INIT=true \
    HOME=/tmp
