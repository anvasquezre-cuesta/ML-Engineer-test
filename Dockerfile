# syntax=docker/dockerfile:1.7

# Keep the Python version in one place so both application stages use the same
# interpreter version.
ARG PYTHON_VERSION=3.12

# Get the uv executable from its official image. This avoids installing uv with
# pip and lets us copy only the binary into the build stage.
FROM ghcr.io/astral-sh/uv:0.9.26 AS uv

# Build the virtual environment separately so build tools and caches are not
# included in the final runtime image.
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

# Compile Python files during installation, copy packages instead of linking
# them, and require uv to use the Python interpreter already in this image.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

# Install third-party dependencies before copying the source code. Docker can
# reuse this layer whenever only application code changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Copy and install the application itself into the prepared virtual environment.
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# Start the final image from a clean Python base rather than the builder image.
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

# Use the virtual environment by default, avoid writing .pyc files at runtime,
# and send application logs directly to Docker without output buffering.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install only the operating-system packages needed at runtime:
# - libgomp1 supports native libraries used by the document-processing stack.
# - Tesseract and its English data provide OCR for scanned documents.
# Then create an unprivileged user so the API does not run as root.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        libgomp1 \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home app

WORKDIR /app

# Bring only the completed application and virtual environment into the runtime
# image, assigning ownership to the unprivileged application user.
COPY --from=builder --chown=app:app /app /app

USER app

# Document the port used by Uvicorn. Docker Compose publishes it to the host.
EXPOSE 8000

# Ask Docker to call the lightweight health endpoint periodically. Using the
# Python standard library avoids adding curl solely for health checks.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

# Start the FastAPI application and listen on every container network interface.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
