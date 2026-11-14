# Pinchana SoundCloud

This FastAPI module extracts supported public SoundCloud tracks and playlists, downloads the resulting audio through the configured network path, and stores files in the shared Pinchana cache.

## API

- `POST /scrape` accepts `{"url":"https://soundcloud.com/artist/track"}`.
- `GET /health` reports service and VPN readiness.

Clients normally call the gateway's `POST /v1/scrape` route instead of this internal module directly.

## Development

```sh
uv sync --frozen
uv run uvicorn pinchana_soundcloud.main:app --host 0.0.0.0 --port 8084 --reload
```

From the parent repository, build with the required shared context:

```sh
docker build --file pinchana-soundcloud/Dockerfile --tag pinchana-soundcloud:local .
```

Public tracks can still fail because of deletion, regional restrictions, authentication requirements, or upstream rate limits. Inspect `/health` and the module logs before changing gateway routing.
