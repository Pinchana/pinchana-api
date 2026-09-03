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

`.github/workflows/docker-publish.yml` builds GHCR images at `ghcr.io/pinchana/pinchana-api/<service>`. `VERSION` is the rolling product CalVer source of truth in `YY.MM.ITERATION` form.

`python scripts/version.py bump` is the normal release-version operation. It initializes and synchronizes all submodules, safely fast-forwards stale submodule pins to their remote default branches, updates Python package metadata and `uv.lock` files, commits and pushes the affected submodules, then commits and pushes `VERSION` plus the new parent submodule pointers. `python scripts/version.py set YY.MM.N` does the same for an explicit version. Use `--local-only` only when a metadata-only edit without git commits/pushes is explicitly required.

To publish in the same operation, use `python scripts/version.py bump --publish -n "release description"` or `-F RELEASE_NOTES.md`. This creates the matching annotated tag and delegates to `scripts/publish_release.py`, which pushes the tag and creates the GitHub Release through `gh`. If the matching tag was already created locally, run `python scripts/publish_release.py -n "release description"` instead. See `docs/RELEASING.md` for the full procedure and safety checks.

Pushes to `main` publish `latest`. An exact matching tag such as `v26.08.1` publishes immutable `26.08.1`, monthly `26.08`, and `stable`. CI rejects mismatched tags, and neither the legacy `stable` branch nor manual dispatch can publish a release channel.

Production hosts update through `python scripts/update_rolling.py --env-file .env`. It atomically pins the newest coherent API release and the current Gluetun image by digest. DLP API and dedicated VPN images are excluded unless `--dlp` is supplied; do not update production images through ad-hoc `docker compose pull` commands.

## Networking & Configuration

Runtime services use `network_mode: container:gluetun`; do not add `ports:` to scraper services. Add ports only to `gluetun` and `.env.example`. Never run `docker restart gluetun`; it clears VPN credentials. Use:

```bash
docker compose up -d --force-recreate gluetun
```

## Commit & Pull Request Guidelines

History uses short imperative or conventional-style messages such as `fix: ...`, `feat: ...`, and `Prepare 0.2 beta release`. For submodule changes, commit and push inside the submodule first, then commit the updated submodule pointer in the root repo. The release scripts automate this ordering for version releases. PRs should describe affected services, runtime/config changes, and verification commands.
