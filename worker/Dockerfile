FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg is required by yt-dlp to extract/convert audio to MP3.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Bring in uv (fast resolver/installer) from its official image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install the pinned dependencies first for better layer caching.
COPY requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

COPY pyproject.toml ./
COPY src/ ./src/

ENTRYPOINT ["python", "src/main.py"]


