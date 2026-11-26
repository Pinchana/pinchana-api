FROM python:3.13-slim

WORKDIR /workspace/scrapers/pinchana-twitter

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy pinchana-core (local path dependency) first
COPY pinchana-core/pyproject.toml pinchana-core/uv.lock pinchana-core/README.md /workspace/pinchana-core/
RUN mkdir -p /workspace/pinchana-core/src
COPY pinchana-core/src /workspace/pinchana-core/src

# Copy scraper package files
COPY scrapers/pinchana-twitter/pyproject.toml scrapers/pinchana-twitter/uv.lock scrapers/pinchana-twitter/README.md ./
RUN uv sync --frozen --no-install-project

COPY scrapers/pinchana-twitter/src ./src
RUN uv sync --frozen

RUN mkdir -p /app/cache
ENV CACHE_PATH=/app/cache
ENV CACHE_MAX_SIZE_GB=10.0

EXPOSE 8089
CMD ["uv", "run", "uvicorn", "pinchana_twitter.main:app", "--host", "0.0.0.0", "--port", "8089"]
