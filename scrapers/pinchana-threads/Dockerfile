FROM python:3.13-slim

WORKDIR /workspace/scrapers/pinchana-threads

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies required by CloakBrowser / Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk-bridge2.0-0 libxss1 libgtk-3-0 \
    libasound2 libxtst6 libgbm1 libxshmfence1 \
    libxcomposite1 libxdamage1 libxrandr2 libpangocairo-1.0-0 \
    fonts-liberation libcurl4 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy pinchana-core (local path dependency) first
COPY pinchana-core/pyproject.toml pinchana-core/uv.lock pinchana-core/README.md /workspace/pinchana-core/
RUN mkdir -p /workspace/pinchana-core/src
COPY pinchana-core/src /workspace/pinchana-core/src

# Copy scraper package files
COPY scrapers/pinchana-threads/pyproject.toml scrapers/pinchana-threads/uv.lock scrapers/pinchana-threads/README.md ./
RUN uv sync --frozen --no-install-project

RUN mkdir -p /app/cache

COPY scrapers/pinchana-threads/src ./src
RUN uv sync --frozen

ENV CACHE_PATH=/app/cache
ENV CACHE_MAX_SIZE_GB=10.0
ENV CLOAKBROWSER_AUTO_UPDATE=false

EXPOSE 8088
CMD ["uv", "run", "uvicorn", "pinchana_threads.main:app", "--host", "0.0.0.0", "--port", "8088"]
