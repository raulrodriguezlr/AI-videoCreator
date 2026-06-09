# syntax=docker/dockerfile:1
#
# VideoCreator backend — local-first runtime image.
#
# Runs the API in `local` mode (SQLite + filesystem + in-process queue), the
# only mode the composition root wires today. All mutable state lives under the
# /data volume so the container itself stays immutable. Server/cloud modes
# (Postgres + Redis + S3) ship once their adapters are wired in the container.
#
# Build from the REPO ROOT (pyproject's readme points at ../README.md):
#   docker build -f backend/Dockerfile -t videocreator-backend .
# Run:
#   docker run --rm -p 8000:8000 -v vc_data:/data videocreator-backend

# --------------------------------------------------------------------------
# Stage 1 — builder: install the package into an isolated virtualenv.
# --------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
# pyproject reads ../README.md for the long description, so it must be present.
COPY README.md ./README.md
COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/src ./backend/src

RUN pip install --upgrade pip && pip install ./backend

# --------------------------------------------------------------------------
# Stage 2 — runtime: slim image with ffmpeg, the venv, and a non-root user.
# --------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# ffmpeg is required by the render/short-composer pipelines.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

# Non-root runtime user owning the data volume.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    APP_MODE=local \
    HOST=0.0.0.0 \
    PORT=8000 \
    PROJECT_ROOT=/data \
    VAR_DIR=/data/var \
    DATABASE_URL=sqlite+aiosqlite:////data/var/app.db \
    STORAGE_URL=file:///data/var/storage \
    LOG_FORMAT=json

WORKDIR /data
USER appuser
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health').status==200 else 1)"

CMD ["uvicorn", "videocreator.interfaces.rest.app:create_app", \
     "--factory", "--host", "0.0.0.0", "--port", "8000"]
