# Pinchana YouTube Music

This FastAPI module extracts audio from supported public `music.youtube.com` URLs and stores the result in the shared Pinchana cache. It is separate from the browser DLP workflow used for ordinary YouTube and `youtu.be` downloads.

## API

- `POST /scrape` accepts `{"url":"https://music.youtube.com/watch?v=VIDEO_ID"}`.
- `GET /health` reports service and VPN readiness.

Clients normally call the gateway's `POST /v1/scrape` route. The v1 response represents the audio as an ordered media asset and may include title, artist, and cover metadata.

## Development

```sh
uv sync --frozen
uv run uvicorn pinchana_ytmusic.main:app --host 0.0.0.0 --port 8085 --reload
```

```sh
# Run from the parent pinchana-api directory.
docker build --file pinchana-ytmusic/Dockerfile --tag pinchana-ytmusic:local .
```

Cookie and proxy configuration must remain outside version control. A public URL can still require authentication or fail because of regional restrictions or upstream rate limits.
