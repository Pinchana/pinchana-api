# Pinchana API

Unified scraping gateway for TikTok and Instagram. Routes requests through a VPN-secured network, caches media locally, and exposes a single HTTP API for all platforms.

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────┐
│   Client    │────▶│  Server (ghcr.io/pinchana/pinchana-api)  │
│             │     │  ┌─────────────┐    ┌─────────────────┐  │
└─────────────┘     │  │ Container   │───▶│ TikTok Scraper  │  │
                    │  │ Registry    │    │   :8081         │  │
                    │  │ (modules)   │───▶│ Instagram       │  │
                    │  └─────────────┘    │   :8082         │  │
                    └─────────────────────┴─────────────────┘  │
                              │
                              ▼
                    ┌─────────────────┐
                    │   Gluetun VPN   │
                    └─────────────────┘
```

- **Server** (`:8080`) — FastAPI gateway. Discovers scrapers from `modules.yaml`, routes `POST /scrape` by URL pattern, proxies to container modules over HTTP.
- **TikTok** (`:8081`) — Standalone yt-dlp-based scraper.
- **Instagram** (`:8082`) — Standalone Playwright-based scraper.
- **Gluetun** — VPN container. All scrapers use `network_mode: container:gluetun` so traffic exits through the VPN tunnel.

## Quick Start (Pre-built Images)

The fastest way to run everything is with the images already published to GitHub Container Registry.

### 1. Clone with submodules

```bash
git clone --recursive https://github.com/Pinchana/pinchana-api.git
cd pinchana-api
```

### 2. Configure environment

Create `.env` (see [Environment Variables](#environment-variables)):

```bash
# Required
NORDVPN_USER=your_nordvpn_username
NORDVPN_PASSWORD=your_nordvpn_password

# Optional
GLUETUN_API_KEY=secret-key
CACHE_MAX_SIZE_GB=10.0
```

### 3. Create module config

```bash
mkdir -p config
cat > config/modules.yaml << 'EOF'
modules:
  tiktok:
    enabled: true
    route_patterns: ["tiktok.com", "vm.tiktok.com", "vt.tiktok.com"]
    source:
      type: local
      path: /modules/pinchana-tiktok
    container:
      dockerfile: Dockerfile
      port: 8081
      endpoint: http://localhost:8081
      image_tag: pinchana-module-tiktok
      container_name: pinchana-tiktok
      network: container:gluetun
      cache_volume: scraper-cache
      env:
        CACHE_MAX_SIZE_GB: "10.0"

  instagram:
    enabled: true
    route_patterns: ["instagram.com", "instagr.am"]
    source:
      type: local
      path: /modules/pinchana-inst
    container:
      dockerfile: Dockerfile
      port: 8082
      endpoint: http://localhost:8082
      image_tag: pinchana-module-inst
      container_name: pinchana-inst
      network: container:gluetun
      cache_volume: scraper-cache
      env:
        CACHE_MAX_SIZE_GB: "10.0"
EOF
```

### 4. Start with pre-built images

Replace the `build:` blocks in `docker-compose.yml` with `image:` references:

```yaml
services:
  server:
    image: ghcr.io/pinchana/pinchana-api/server:latest
    # remove: build: ...

  tiktok:
    image: ghcr.io/pinchana/pinchana-api/tiktok:latest
    # remove: build: ...

  instagram:
    image: ghcr.io/pinchana/pinchana-api/instagram:latest
    # remove: build: ...
```

Or use an override file:

```bash
cat > docker-compose.override.yml << 'EOF'
services:
  server:
    image: ghcr.io/pinchana/pinchana-api/server:latest
    build: !reset null
  tiktok:
    image: ghcr.io/pinchana/pinchana-api/tiktok:latest
    build: !reset null
  instagram:
    image: ghcr.io/pinchana/pinchana-api/instagram:latest
    build: !reset null
EOF

docker compose up -d
```

> **Note:** GHCR packages are tied to the repository visibility. If the images are private, log in first:  
> `echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin`

### 5. Verify

```bash
curl http://localhost:8080/health
```

## Local Development (Build from Source)

If you want to build the images locally instead of pulling from GHCR:

```bash
# Make sure submodules are up to date
git submodule update --init --recursive

# Build and start everything
docker compose up --build -d
```

### Rebuild a single service

```bash
docker compose build tiktok
docker compose up -d tiktok
```

## API Usage

### Scrape a URL

```bash
curl -X POST http://localhost:8080/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.tiktok.com/@username/video/1234567890"}'
```

Response:

```json
{
  "shortcode": "1234567890",
  "caption": "Video caption...",
  "author": "@username",
  "media_type": "video",
  "thumbnail_url": "https://...",
  "video_url": "https://...",
  "carousel": null
}
```

### Health Check

```bash
curl http://localhost:8080/health
```

### Admin Endpoints (when `CONTAINER_MODE=true`)

```bash
# List modules
curl http://localhost:8080/admin/modules

# Start / stop a module container
curl -X POST http://localhost:8080/admin/modules/tiktok/start
curl -X POST http://localhost:8080/admin/modules/tiktok/stop
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NORDVPN_USER` | Yes* | — | NordVPN username |
| `NORDVPN_PASSWORD` | Yes* | — | NordVPN password |
| `WIREGUARD_PRIVATE_KEY` | Alt* | — | WireGuard private key (instead of OpenVPN) |
| `SERVER_COUNTRIES` | No | — | Comma-separated VPN server countries |
| `VPN_SERVICE_PROVIDER` | No | `nordvpn` | VPN provider for Gluetun |
| `GLUETUN_API_KEY` | No | `secret-key` | API key for Gluetun control server |
| `CACHE_MAX_SIZE_GB` | No | `10.0` | Max cache size in GB |
| `CONTAINER_MODE` | No | `false` | Enable container lifecycle management in server |
| `MODULES_CONFIG` | No | `/app/config/modules.yaml` | Path to module routing config |

\* Either NordVPN credentials **or** a WireGuard private key is required for Gluetun.

## Module Routing

The server routes scrape requests automatically based on URL patterns defined in `modules.yaml`:

| URL Contains | Routed To |
|--------------|-----------|
| `tiktok.com`, `vm.tiktok.com`, `vt.tiktok.com` | TikTok scraper (`:8081`) |
| `instagram.com`, `instagr.am` | Instagram scraper (`:8082`) |

You can add new modules by extending `config/modules.yaml` and providing a matching container image.

## Repository Structure

```
pinchana-api/
├── pinchana-core/      # Shared models, storage, VPN, plugin registry, Docker manager
├── pinchana-server/    # Unified gateway (FastAPI)
├── pinchana-tiktok/    # TikTok scraper module
├── pinchana-inst/      # Instagram scraper module
├── config/             # Runtime configuration (modules.yaml)
├── docker-compose.yml  # Local orchestration
└── .github/workflows/  # CI/CD for GHCR
```

## Contributing

Each service is a standalone Python package managed by `uv`. To work on a module:

```bash
cd pinchana-tiktok
uv sync
uv run python -m pinchana_tiktok.main
```

Make sure to commit submodule changes from within the submodule directory, then update the parent repo's submodule pointers.

## License

MIT
