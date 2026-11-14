# Pinchana Deezer

This FastAPI module extracts supported public Deezer tracks and playlists, downloads audio through the configured network path, and stores the result in the shared Pinchana cache.

## API

- `POST /scrape` accepts `{"url":"https://www.deezer.com/track/TRACK_ID"}` and supported Deezer short-link domains.
- `GET /health` reports service and VPN readiness.

Clients normally call the gateway's authenticated `POST /v1/scrape` route rather than this internal service.

## Development

```sh
uv sync --frozen
uv run uvicorn pinchana_deezer.main:app --host 0.0.0.0 --port 8087 --reload
```

```sh
# Run from the parent pinchana-api directory.
docker build --file pinchana-deezer/Dockerfile --tag pinchana-deezer:local .
```

Public links can still fail because of deletion, regional restrictions, upstream authentication requirements, or rate limits.
