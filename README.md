# Pinchana API

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![Publish Docker images](https://github.com/Pinchana/pinchana-api/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Pinchana/pinchana-api/actions/workflows/docker-publish.yml)

Pinchana is a Docker Compose based scraping gateway. A central FastAPI server accepts one `/scrape` request shape, detects the target platform, and forwards the job to a specialized scraper service. The production stack routes outbound scraper traffic through Gluetun; the development stack can run without VPN credentials.

## Supported Services

| Service | Port | Routes |
| --- | ---: | --- |
| server | 8080 | Gateway API |
| tiktok | 8081 | `tiktok.com`, `vm.tiktok.com`, `vt.tiktok.com` |
| instagram | 8082 | `instagram.com`, `instagr.am` |
| shorts | 8083 | `youtube.com/shorts` |
| soundcloud | 8084 | `soundcloud.com`, `on.soundcloud.com` |
| ytmusic | 8085 | `music.youtube.com` |
| spotify | 8086 | `open.spotify.com` |
| deezer | 8087 | `deezer.com`, Deezer link domains |
| threads | 8088 | `threads.net` |
| twitter | 8089 | `x.com`, `twitter.com`, `vxtwitter.com`, `fxtwitter.com` |

Gluetun's control API is exposed on port `8000`.

## Repository Layout

This root repository only orchestrates submodules and Docker Compose. Each `pinchana-*` directory is an independent Python package with `pyproject.toml`, `uv.lock`, `Dockerfile`, and `src/pinchana_<name>/`.

`pinchana-core` contains shared models, storage, music helpers, Docker orchestration helpers, and Gluetun control logic. Every service depends on it through a local uv path dependency.

## Quick Start

Clone with submodules:

```bash
git clone --recursive https://github.com/Pinchana/pinchana-api.git
cd pinchana-api
```

Create configuration:

```bash
cp .env.example .env
```

For the production stack, set at least:

```env
WIREGUARD_PRIVATE_KEY=your_nordlynx_private_key
```

For Spotify scraping, also set:

```env
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
```

Run prebuilt GHCR images:

```bash
docker compose up -d
```

Build from source without a VPN (each service binds its own development port):

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

Check health:

```bash
curl http://localhost:8080/health
```

## API Usage

```bash
curl -X POST http://localhost:8080/scrape \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $PINCHANA_API_KEY" \
  -d '{"url": "https://www.instagram.com/p/SHORTCODE/"}'
```

The same endpoint accepts supported TikTok, YouTube Shorts, SoundCloud, YouTube Music, Spotify, Deezer, Threads, Twitter/X, and Instagram URLs. Configure independently revocable machine keys with `PINCHANA_API_KEYS`, a JSON object such as `{"bot":"secret","automation":"other-secret"}`. Machine requests to `/scrape`, `/v1/scrape`, `/media/...`, and `/admin/...` must include `X-API-Key`.

New integrations should use the versioned response contract:

```bash
curl -X POST http://localhost:8080/v1/scrape \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $PINCHANA_API_KEY" \
  -d '{"url": "https://www.instagram.com/p/SHORTCODE/"}'
```

`/v1/scrape` returns `{data, meta}`. Source, content, author, engagement, safety,
music, and link metadata are grouped, while all downloadable images, videos,
audio, covers, and slideshow soundtracks live in one ordered `data.media` array.
Each image or video includes `dimensions: {width, height}` when the cached file
can be inspected. V1 errors use a stable `{error: {code, message, details}}`
envelope. The flat `/scrape` response remains available for existing clients.

Browser clients use the isolated web flow:

1. `GET /web/identity` publishes an optional project-issued instance certificate.
2. `POST /web/verify` exchanges a one-use Turnstile token for a signed session.
3. `GET /web/session` validates that bearer session.
4. `POST /v1/web/scrape` returns the normalized v1 contract and `GET /web/media/...` serves its protected assets without exposing a machine API key. Legacy `/web/scrape` remains available for older clients.

The official web client accepts custom origins only with an origin-bound,
unexpired certificate. See [the instance trust model](docs/INSTANCE_TRUST.md).

Browser-encrypted private downloads use the optional asynchronous DLP profile,
not the normal `/scrape` module router. Keep `DLP_ENABLED=false` until its
internal services and immutable images pass the [production rollout
preflight](docs/DLP_PRODUCTION_ROLLOUT.md).

Set the widget's private key as `TURNSTILE_SECRET_KEY`; the API calls Cloudflare Siteverify directly and never exposes this key to the web application. Set `TURNSTILE_EXPECTED_HOSTNAME` to the production web hostname and keep `TURNSTILE_EXPECTED_ACTION=turnstile-spin-v1`. Use a random `TURNSTILE_SESSION_SECRET` of at least 32 characters. Sessions default to 12 hours and are capped at 24 hours.

When one of Cloudflare's documented public test secrets is configured for local development, the API still requires `success=true` but skips hostname and action checks because dummy validation responses do not carry production widget metadata. Production secrets always enforce the configured hostname and action.

Admin endpoints:

- `GET /health`
- `GET /admin/vpn/status`
- `POST /admin/vpn/rotate`
- `GET /admin/modules`

## Configuration Notes

In `docker-compose.yml`, all scraper and server containers use:

```yaml
network_mode: container:gluetun
```

Do not add `ports:` to production scraper services. Publish new production service ports on `gluetun` and mirror them in `.env.example`. `docker-compose.dev.yml` uses a normal bridge network, direct service ports, Compose DNS names, and `VPN_ENABLED=false`.

Never run `docker restart gluetun`; it can clear VPN credentials and cause `AUTH_ERROR`. Recreate it instead:

```bash
docker compose up -d --force-recreate gluetun
```

Shorts can use YouTube cookies from `SHORTS_COOKIES_DIR` mounted read-only to `/run/pinchana-cookies`. `SHORTS_MAX_MB_PER_MINUTE` controls optional MP4 re-encoding for oversized output.

## Development

Work inside submodules:

```bash
cd pinchana-inst
uv sync
uv run uvicorn pinchana_inst.main:app --reload
uv run python -c "import pinchana_inst; print('ok')"
```

Run Instagram tests:

```bash
cd pinchana-inst
uv run pytest
PINCHANA_INST_LIVE=1 uv run pytest
```

Docker builds must use the repo root as build context:

```bash
docker build -f pinchana-inst/Dockerfile -t pinchana-inst .
```

## Releases and Images

Images are published to:

```text
ghcr.io/pinchana/pinchana-api/<service>:<tag>
```

Current tag policy:

- Push to `main`: publishes `latest`.
- Push to `stable`: publishes `stable`.
- Push tag such as `v0.2.beta`: publishes `0.2.beta` and `stable`.
- Manual workflow dispatch supports explicit `services`, `release_version`, and `publish_stable`.

Python package versions use PEP 440. The `0.2.beta` Docker release is represented in submodule `pyproject.toml` files as `0.2b0`.

## Adding a Module

Adding a service requires coordinated changes:

1. Add a new `pinchana-<name>` submodule with `src/pinchana_<name>/main.py`.
2. Add routing and container metadata in `config/modules.yaml`.
3. Add services to `docker-compose.yml` and `docker-compose.dev.yml`.
4. Add ports, endpoints, and container names to `.env.example`.
5. Add workflow detection and Dockerfile mapping in `.github/workflows/docker-publish.yml`.

## License

MIT. See `LICENSE`.
