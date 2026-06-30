# Repository Guidelines

## Project Structure & Module Organization

This is a Docker Compose orchestration repo for the Pinchana scraping gateway. The root is not a Python package and has no root task runner. Each `pinchana-*` directory is an independent git submodule with its own `pyproject.toml`, `uv.lock`, `Dockerfile`, and `src/pinchana_<name>/` package. `pinchana-core` is shared by every service.

Ports: server `8080`, tiktok `8081`, inst `8082`, shorts `8083`, soundcloud `8084`, ytmusic `8085`, spotify `8086`, deezer `8087`, threads `8088`, twitter `8089`, gluetun control `8000`.

## Build, Test, and Development Commands

Work inside a submodule for Python development:

```bash
cd pinchana-<name>
uv sync
uv run uvicorn pinchana_<name>.main:app --reload
uv run python -c "import pinchana_<name>; print('ok')"
```

Build Docker images from the repo root because Dockerfiles copy `pinchana-core/` and the target service:

```bash
docker build -f pinchana-inst/Dockerfile -t pinchana-inst .
docker compose up -d
docker compose -f docker-compose.dev.yml up -d --build
```

Both compose files require `.env` with `WIREGUARD_PRIVATE_KEY`; start from `.env.example`.

## Coding Style & Naming Conventions

Use Python 3.13+, async I/O for network work, and package names matching `pinchana_<name>`. FastAPI apps live at `pinchana_<name>.main:app`. Never commit `__pycache__/` or `*.pyc`. There is no repo-wide formatter, Ruff, mypy, or lint config, so do not invent root lint commands.

## Testing Guidelines

Tests are sparse. `pinchana-inst` has pytest coverage; live Instagram cases are skipped unless enabled:

```bash
cd pinchana-inst
uv run pytest
PINCHANA_INST_LIVE=1 uv run pytest
```

For other modules, verify by importing the package or running the service locally.

## CI, Releases & Docker Tags

`.github/workflows/docker-publish.yml` builds GHCR images at `ghcr.io/pinchana/pinchana-api/<service>`. Pushes to `main` publish `latest`; pushes to `stable` publish `stable`; release tags like `v0.2.beta` publish both `0.2.beta` and `stable`. Manual dispatch supports `services`, `release_version`, and `publish_stable`.

Python package versions use PEP 440, so the `0.2.beta` Docker release is represented in submodule `pyproject.toml` files as `0.2b0`.

## Networking & Configuration

Runtime services use `network_mode: container:gluetun`; do not add `ports:` to scraper services. Add ports only to `gluetun` and `.env.example`. Never run `docker restart gluetun`; it clears VPN credentials. Use:

```bash
docker compose up -d --force-recreate gluetun
```

## Commit & Pull Request Guidelines

History uses short imperative or conventional-style messages such as `fix: ...`, `feat: ...`, and `Prepare 0.2 beta release`. For submodule changes, commit and push inside the submodule first, then commit the updated submodule pointer in the root repo. PRs should describe affected services, runtime/config changes, and verification commands.
