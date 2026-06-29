# AGENTS.md

Repo-wide guide for OpenCode agents. Per-module details live in each submodule; `pinchana-inst/AGENTS.md` exists but is **stale** (describes a removed `app/` layout) — trust the source tree over it.

## What this repo is

- A **Docker Compose orchestration repo** for a unified scraping gateway. The root has **no Python project, no Makefile, no task runner, no `opencode.json`**. Don't look for root-level build/test/lint commands — there are none.
- Each `pinchana-*` directory is an **independent git submodule** (see `.gitmodules`) with its own `pyproject.toml`, `uv.lock`, and `Dockerfile`. `pinchana-core` is the shared library every other module depends on.
- Clone with `git clone --recursive`; recover missing submodules with `git submodule update --init --recursive`.

## Per-module development (uv, Python 3.13+)

Work **inside the submodule directory**, not the repo root:

```bash
cd pinchana-<name>
uv sync                                              # requires ../pinchana-core present (local path dep)
uv run uvicorn pinchana_<name>.main:app --reload     # entrypoint pattern; underscore = package name
```

- All submodules use a `src/pinchana_<name>/` layout. The FastAPI app object is `pinchana_<name>.main:app`.
- `pinchana-core` is wired via `[tool.uv.sources] pinchana-core = { path = "../pinchana-core" }` in every submodule. `uv sync` fails if `pinchana-core` isn't checked out beside the submodule.
- **Changing `pinchana-core` forces a full rebuild of every service** (CI treats it as a global dependency).

## Docker builds: context is the repo root

Every Dockerfile copies `pinchana-core/` then `pinchana-<name>/` using paths relative to the repo root, so you **must build from the repo root**:

```bash
docker build -f pinchana-tiktok/Dockerfile -t pinchana-tiktok .   # from repo root
```

Building from inside the submodule directory breaks the `COPY` paths.

## Running the stack

- `docker-compose.yml` — prebuilt GHCR images (prod). `docker compose up -d`.
- `docker-compose.dev.yml` — build from source. `docker compose -f docker-compose.dev.yml up -d --build`.
- Both **require `.env` with `WIREGUARD_PRIVATE_KEY`** (NordVPN NordLynx). Copy from `.env.example`.

## Networking: gluetun owns everything

- All services run with `network_mode: container:gluetun`. gluetun publishes **all** ports: `8080` server, `8081`-`8089` modules, `8000` gluetun control. Scraper/server containers have **no `ports:` of their own** and no direct internet — all egress goes through the VPN.
- Don't add `ports:` to scraper services; add new ports to the `gluetun` service and to `.env.example`.
- **Never `docker restart gluetun`** — it wipes VPN creds from memory and causes `AUTH_ERROR`. Use `docker compose up -d --force-recreate gluetun`. Programmatic rotation via `POST /admin/vpn/rotate` is safe.

## Server routing model

`pinchana-server` resolves `/scrape` by matching the URL against `route_patterns` in `config/modules.yaml`:

- `CONTAINER_MODE=true` (dev default): server builds/start/stops scraper containers itself via the Docker socket (`/var/run/docker.sock` mounted), reading `config/modules.yaml`.
- `CONTAINER_MODE=false` (prod compose default): server forwards `/scrape` to each module's HTTP `endpoint` (from `MODULE_*_ENDPOINT` env vars); modules are managed by compose.
- Optional in-process plugins: set `IN_PROCESS_PLUGINS=comma,of,importable,names` to `importlib.import_module` scrapers directly into the server (mounts their routers under `/<name>`).

## Adding a new module touches many files

1. New `pinchana-<name>/` submodule with `src/pinchana_<name>/main.py` exposing `app`.
2. `config/modules.yaml` — add `route_patterns`, port, endpoint.
3. `docker-compose.yml` **and** `docker-compose.dev.yml` — add a service with `network_mode: container:gluetun`, `depends_on: gluetun`, and the `scraper-cache` volume.
4. `.env.example` — add `*_HOST_PORT`, `MODULE_*_PORT`, `MODULE_*_ENDPOINT`, `*_CONTAINER_NAME`.
5. `.github/workflows/docker-publish.yml` — add the service to the `detect` job list **and** the `map` step; add to `.gitmodules`.

Port assignments: server 8080, tiktok 8081, inst 8082, shorts 8083, soundcloud 8084, ytmusic 8085, spotify 8086, deezer 8087, threads 8088, twitter 8089, gluetun control 8000.

## Tooling & tests

- **No lint, typecheck, ruff, mypy, or formatter config exists anywhere.** There is no CI test/lint job. CI (`.github/workflows/docker-publish.yml`) only builds and pushes Docker images to `ghcr.io/pinchana/pinchana-api/<service>:latest`. Don't invent `npm run lint`-style commands; if asked to verify, run the app or `uv run python -c "import ..."`.
- CI rebuilds selectively on push to `main` (only services whose submodule changed); changes to `pinchana-core/`, `docker-compose.yml`, or the workflow rebuild everything; tags `v*.*.*` build all services.
- **Tests are effectively absent.** Only `pinchana-inst` has a `tests/` dir, and `tests/test_scrapers.py` is currently **broken** — it imports `from app.scraper` / `from app.playwright_scraper`, but the package moved to `src/pinchana_inst/` (no `app/` dir, no `playwright_scraper` module). It will fail at collection. The tests were live integration tests against real Instagram requiring a Gluetun sidecar (they `pytest.skip()` on 403/429). `pinchana-threads` and `pinchana-twitter` declare pytest dev deps but ship no test files.

## Module-specific runtime needs

- **shorts**: requires `ffmpeg` (installed in its Dockerfile) and YouTube cookies mounted read-only from `SHORTS_COOKIES_DIR` (default `./secrets/yt-cookies`) → `/run/pinchana-cookies`. `SHORTS_MAX_MB_PER_MINUTE` re-encodes oversized output.
- **spotify**: requires `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `.env`.
