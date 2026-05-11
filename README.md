# 🐘 Pinchana API

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![Publish Docker images](https://github.com/Pinchana/pinchana-api/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Pinchana/pinchana-api/actions/workflows/docker-publish.yml)

**Pinchana** is a unified, high-performance scraping gateway designed to extract media from TikTok, Instagram, and YouTube Shorts reliably. It solves common scraping challenges by routing all traffic through a rotating VPN (via [Gluetun](https://github.com/qdm12/gluetun)) and employing advanced bypass techniques.

---

## 📖 Table of Contents

- [✨ Key Features](#-key-features)
- [🏗 Architecture](#-architecture)
- [📂 Repository Structure](#-repository-structure)
- [🚀 Quick Start](#-quick-start)
- [⚙️ Configuration](#-configuration)
- [📡 API Usage](#-api-usage)
- [🛠 Development](#-development)
- [📜 License](#-license)

---

## ✨ Key Features

- **🎯 Unified API:** A single gateway (`/scrape`) to handle different social media platforms.
- **🛡 VPN-First Design:** Zero-trust networking. Scrapers have no direct internet access; all traffic *must* exit through the VPN.
- **🔄 Smart Rotation:** Automatic IP rotation when rate limits (403/429) are detected.
- **💾 Global Media Cache:** Persistent LRU (Least Recently Used) cache for images and videos to save bandwidth and avoid re-scraping.
- **🧩 Extensible Architecture:** Easily add new scraper modules by defining simple route patterns.
- **🐳 Container Managed:** Optional auto-lifecycle management for scraper containers via the gateway.

---

## 🏗 Architecture

Pinchana follows a modular architecture where a central gateway routes requests to specialized scraper modules.

```mermaid
graph TD
    Client[Client] -->|POST /scrape| Gateway[Pinchana Server :8080]
    Gateway -->|Route by Pattern| Modules{Module Registry}
    
    subgraph "Internal Network (VPN Secured)"
        Modules -->|Proxy| TikTok[TikTok Scraper :8081]
        Modules -->|Proxy| Instagram[Instagram Scraper :8082]
        Modules -->|Proxy| Shorts[YouTube Shorts Scraper :8083]
        
        TikTok -->|Traffic| Gluetun[Gluetun VPN]
        Instagram -->|Traffic| Gluetun
        Shorts -->|Traffic| Gluetun
    end
    
    Gluetun -->|Encrypted Tunnel| Internet((Internet))
    
    TikTok -.->|Save| Cache[(LRU Media Cache)]
    Instagram -.->|Save| Cache
```

- **Pinchana Server:** FastAPI gateway. Manages module discovery, request routing, and optional container lifecycle.
- **Scraper Modules:** Standalone services (TikTok, Instagram, YouTube Shorts) that perform the actual extraction.
- **Gluetun:** VPN sidecar ensuring all outgoing traffic is protected and rotatable.
- **Pinchana Core:** Shared library providing models, storage logic, and VPN signaling.

---

## 📂 Repository Structure

The project is organized as a monorepo with submodules for each component:

| Directory | Component | Description |
|-----------|-----------|-------------|
| [`pinchana-server/`](./pinchana-server) | **Gateway** | Central FastAPI router and module manager. |
| [`pinchana-core/`](./pinchana-core) | **Core** | Shared logic: LRU Cache, VPN control, Docker orchestration. |
| [`pinchana-inst/`](./pinchana-inst) | **Instagram** | High-performance scraper (GraphQL + Playwright fallback). |
| [`pinchana-tiktok/`](./pinchana-tiktok) | **TikTok** | Custom yt-dlp based extractor for TikTok media. |
| [`pinchana-shorts/`](./pinchana-shorts) | **YouTube Shorts** | yt-dlp based extractor with secure cookie loading and size-aware MP4 output. |
| `config/` | **Config** | Runtime configuration (e.g., `modules.yaml`). |

---

## 🚀 Quick Start

### 1. Clone the Repository
Ensure you clone with submodules to get all components:
```bash
git clone --recursive https://github.com/Pinchana/pinchana-api.git
cd pinchana-api
```

### 2. Configure Environment
Create a `.env` file from the example:
```bash
cp .env.example .env
```
Add your **NordVPN WireGuard Private Key** (NordLynx):
```env
WIREGUARD_PRIVATE_KEY=your_private_key_here
```
*(See [Configuration](#-extracting-your-nordvpn-wireguard-private-key) for instructions on how to get this key.)*

### 3. Run with Docker Compose
To run using pre-built images from GHCR (default):
```bash
docker compose up -d
```
To build and run locally from source:
```bash
docker compose -f docker-compose.dev.yml up -d --build
```
This will start the Gateway, Scrapers, and VPN.

### 4. Verify Installation
```bash
curl http://localhost:8080/health
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WIREGUARD_PRIVATE_KEY` | **Yes** | — | Your VPN WireGuard private key. |
| `SERVER_COUNTRIES` | No | — | Comma-separated list of countries (e.g., `Netherlands,Germany`). |
| `CACHE_MAX_SIZE_GB` | No | `10.0` | Maximum size for the media cache. |
| `CONTAINER_MODE` | No | `true` | Enable container management features in the gateway. |
| `SHORTS_COOKIES_DIR` | No | `./secrets/yt-cookies` | Host directory containing YouTube cookies files (mounted read-only). |
| `SHORTS_MAX_MB_PER_MINUTE` | No | `18.0` | Soft size target for Shorts output; bigger files are re-encoded. |

### 🔐 Secure YouTube Cookies Mount (read-only)
1. Create a local secrets folder and keep it out of git:
   ```bash
   mkdir -p ./secrets/yt-cookies
   chmod 700 ./secrets ./secrets/yt-cookies
   ```
2. Place your exported Netscape cookie file there (e.g. `youtube.com_cookies.txt`) and tighten file permissions:
   ```bash
   chmod 600 ./secrets/yt-cookies/*.txt
   ```
3. Keep `SHORTS_COOKIES_DIR=./secrets/yt-cookies` in `.env`.

The Shorts module mounts this folder as read-only and copies cookies into an ephemeral `/tmp` file for yt-dlp runtime use, so the mounted source is not modified.

### 🔑 Extracting your NordVPN WireGuard Private Key
1. Connect to NordVPN using the CLI: `nordvpn connect`.
2. Run: `sudo wg show nordlynx private-key`.
3. Copy the output to your `.env` file.

---

## 📡 API Usage

### Scrape a URL
The gateway automatically detects the platform based on the URL.

```bash
curl -X POST http://localhost:8080/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.tiktok.com/@username/video/1234567890"}'

# YouTube Shorts example
curl -X POST http://localhost:8080/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/shorts/VIDEO_ID"}'
```

### Admin Endpoints
- `POST /admin/vpn/rotate`: Trigger an immediate IP change.
- `GET /admin/vpn/status`: Check current VPN health and IP.
- `GET /admin/modules`: List active scraper modules.

---

## 🛠 Development

### Using `uv` for Package Management
Each sub-project is a standalone Python package managed by [uv](https://github.com/astral-sh/uv).

```bash
cd pinchana-server
uv sync
uv run uvicorn src.pinchana_server.main:app --reload
```

### Adding a New Module
1. Create a new directory (e.g., `pinchana-youtube`).
2. Implement the `/scrape` endpoint returning the standard `ScrapeResponse` model.
3. Add the module configuration to `config/modules.yaml`.

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.
