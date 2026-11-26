FROM python:3.13-slim

WORKDIR /workspace/scrapers/pinchana-tiktok

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy pinchana-core (local path dependency) first
COPY pinchana-core/pyproject.toml pinchana-core/uv.lock pinchana-core/README.md /workspace/pinchana-core/
RUN mkdir -p /workspace/pinchana-core/src
COPY pinchana-core/src /workspace/pinchana-core/src

# Copy scraper package files
COPY scrapers/pinchana-tiktok/pyproject.toml scrapers/pinchana-tiktok/uv.lock scrapers/pinchana-tiktok/README.md ./
RUN uv sync --frozen --no-install-project

COPY scrapers/pinchana-tiktok/src ./src

RUN mkdir -p /app/cache
ENV CACHE_PATH=/app/cache
ENV CACHE_MAX_SIZE_GB=10.0

EXPOSE 8081
CMD ["uv", "run", "uvicorn", "pinchana_tiktok.main:app", "--host", "0.0.0.0", "--port", "8081"]
