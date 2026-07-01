# Pinchana API

> [!WARNING]
> The Live Photo implementation on this branch currently does not work at all. It is exploration and experimentation for TikTok Live Photo scraping behavior, not production-ready functionality.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![Publish Docker images](https://github.com/Pinchana/pinchana-api/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Pinchana/pinchana-api/actions/workflows/docker-publish.yml)

Pinchana is a Docker Compose based scraping gateway. A central FastAPI server accepts one `/scrape` request shape, detects the target platform, and forwards the job to a specialized scraper service. All services share Gluetun's network namespace, so outbound traffic goes through the VPN.

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

Set at least:

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

Build from source instead:

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
  -d '{"url": "https://www.instagram.com/p/SHORTCODE/"}'
```

The same endpoint accepts supported TikTok, YouTube Shorts, SoundCloud, YouTube Music, Spotify, Deezer, Threads, Twitter/X, and Instagram URLs.

Admin endpoints:

- `GET /health`
- `GET /admin/vpn/status`
- `POST /admin/vpn/rotate`
- `GET /admin/modules`

## Configuration Notes

All scraper and server containers use:

```yaml
network_mode: container:gluetun
```

Do not add `ports:` to scraper services. Publish new service ports on `gluetun` and mirror them in `.env.example`.

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
