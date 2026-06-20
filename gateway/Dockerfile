FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Bring in uv (fast resolver/installer) from its official image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install the pinned dependencies first for better layer caching.
COPY requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

COPY pyproject.toml ./
COPY src/ ./src/

# Cloud Run injects $PORT; default to 8080 for local runs.
ENV PORT=8080
CMD exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT}
