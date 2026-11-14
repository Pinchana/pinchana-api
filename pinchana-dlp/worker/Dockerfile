FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin worker

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt
COPY --chown=worker:worker main.py .

USER worker
CMD ["python", "main.py"]
