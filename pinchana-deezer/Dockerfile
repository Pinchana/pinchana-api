FROM python:3.13-slim

WORKDIR /workspace/pinchana-deezer

RUN apt-get update && apt-get install -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pinchana-core/pyproject.toml pinchana-core/uv.lock pinchana-core/README.md ../pinchana-core/
RUN mkdir -p ../pinchana-core/src
COPY pinchana-core/src ../pinchana-core/src

COPY pinchana-deezer/pyproject.toml pinchana-deezer/uv.lock pinchana-deezer/README.md ./
RUN uv sync --frozen --no-install-project

COPY pinchana-deezer/src ./src

RUN mkdir -p /app/cache
ENV CACHE_PATH=/app/cache
ENV CACHE_MAX_SIZE_GB=10.0

EXPOSE 8087
CMD ["uv", "run", "uvicorn", "pinchana_deezer.main:app", "--host", "0.0.0.0", "--port", "8087"]
