# Pinchana API

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![Publish Docker images](https://github.com/Pinchana/pinchana-api/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Pinchana/pinchana-api/actions/workflows/docker-publish.yml)

Pinchana API is a Docker Compose-based media extraction gateway. A central FastAPI server accepts the versioned `/v1/scrape` request, selects a platform module, and returns a normalized response. The production stack routes outbound scraper traffic through Gluetun; the development stack can run without VPN credentials. The unversioned `/scrape` route remains available for existing integrations.

## Supported services

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
| threads | 8088 | `threads.net`, `threads.com` |
| twitter | 8089 | `x.com`, `twitter.com`, `vxtwitter.com`, `fxtwitter.com` |
| coub | 8090 | `coub.com/view`, `coub.com/embed` |

Gluetun's control API is exposed on port `8000`.

## Repository layout

This root repository only orchestrates submodules and Docker Compose. Each `pinchana-*` directory is an independent Python package with `pyproject.toml`, `uv.lock`, `Dockerfile`, and `src/pinchana_<name>/`.

`pinchana-core` contains shared models, storage, music helpers, Docker orchestration helpers, and Gluetun control logic. Every service depends on it through a local uv path dependency.

## Quick start

Clone with submodules:

```bash
git clone --recurse-submodules https://github.com/Pinchana/pinchana-api.git
cd pinchana-api
```

Create configuration:

```bash
cp .env.example .env
chmod 600 .env
```

For the production stack, set at least the API key and VPN credentials. NordVPN
manual connections should use the service username and password shown under
Nord Account's Manual setup page:

```env
VPN_SERVICE_PROVIDER=nordvpn
VPN_TYPE=openvpn
OPENVPN_USER=REPLACE_WITH_NORDVPN_SERVICE_USERNAME
OPENVPN_PASSWORD=REPLACE_WITH_NORDVPN_SERVICE_PASSWORD
OPENVPN_PROTOCOL=tcp
PINCHANA_API_KEYS={"automation":"REPLACE_WITH_LONG_RANDOM_MACHINE_KEY"}
```

Do not use the Nord Account password or access token as the OpenVPN password.
Providers that still issue supported manual WireGuard keys can instead set
`VPN_TYPE=wireguard` and `WIREGUARD_PRIVATE_KEY`.

For Spotify scraping, also set:

```env
SPOTIFY_CLIENT_ID=REPLACE_WITH_CLIENT_ID
SPOTIFY_CLIENT_SECRET=REPLACE_WITH_CLIENT_SECRET
```

Run prebuilt GHCR images:

```bash
python scripts/update_rolling.py --env-file .env
docker compose --env-file .env config --quiet
docker compose --env-file .env up --detach
```

This is the supported production update path. It discovers the newest coherent
CalVer release through the rolling `stable` channel, resolves Gluetun's stable
`v3` release channel, and atomically stores immutable image digests in `.env`. By
default it updates the main Gluetun, gateway, and scraper APIs. Add `--dlp` to
include all three DLP images and its dedicated Gluetun image; without that flag,
DLP values are untouched.

Build from source without a VPN (each service binds its own development port):

```bash
docker compose --env-file .env -f docker-compose.dev.yml up --detach --build
```

Check health:

```bash
curl --fail-with-body --silent --show-error http://localhost:8080/health
```

## API Usage

```bash
curl --fail-with-body --silent --show-error \
  --request POST http://localhost:8080/v1/scrape \
  --header 'Content-Type: application/json' \
  --header 'X-API-Key: REPLACE_WITH_MACHINE_KEY' \
  --data '{"url":"https://www.instagram.com/p/REPLACE_WITH_PUBLIC_SHORTCODE/"}'
```

The same endpoint accepts supported TikTok, YouTube Shorts, SoundCloud, YouTube Music, Spotify, Deezer, Threads, Twitter/X, Coub, and Instagram URLs. Configure independently revocable machine keys with `PINCHANA_API_KEYS`, a JSON object such as `{"bot":"secret","automation":"other-secret"}`. Machine requests to `/v1/scrape`, legacy `/scrape`, `/media/...`, and `/admin/...` must include `X-API-Key`.

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

Native clients never receive a machine API key. Mobile authentication is
optional by default: scrape, cached media, and capability routes accept
anonymous requests and validate scoped installation tokens when supplied.
Set `MOBILE_AUTH_REQUIRED=true` to require those tokens. Private DLP routes
always require an authenticated installation because the installation identity
is their job-ownership boundary.

When enabled, the mobile installation grant flow is:

1. `POST /v1/mobile/challenges` creates a short-lived, single-use challenge.
2. `POST /v1/mobile/grants` consumes the challenge and returns a 15-minute
   scoped access token plus a rotating refresh token.
3. `POST /v1/mobile/session/refresh` rotates the refresh token; reuse revokes
   the complete token family.
4. Mobile scrape, media, and capability routes accept the token optionally;
   DLP routes require it and enforce their required scope.

Grant and refresh state is stored in `MOBILE_SESSION_DB_PATH`, which defaults to
the server's persistent cache volume. The current production Compose default is
`MOBILE_AUTH_MODE=guest`: this issues revocable, scoped installation sessions
without requiring App Store or Play Store attestation and without placing a
machine key in the app. Optional `attested` mode can later delegate App Attest
and Play Integrity validation to `MOBILE_ATTESTATION_URL`. The former static-key
`/v1/mobile/verify` exchange is retired; `/v1/mobile/attest` remains as a
deprecated alias for `/v1/mobile/grants`. See
[mobile installation authentication](docs/MOBILE_AUTH.md) for operational
requirements.

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
docker compose --env-file .env up --detach --force-recreate gluetun
```

Shorts can use YouTube cookies from `SHORTS_COOKIES_DIR` mounted read-only to `/run/pinchana-cookies`. `SHORTS_MAX_MB_PER_MINUTE` controls optional MP4 re-encoding for oversized output.

## Development

Work inside submodules:

```bash
cd pinchana-inst
uv sync --frozen
uv run uvicorn pinchana_inst.main:app --reload
uv run python -c "import pinchana_inst; print('ok')"
```

Run Instagram tests:

```bash
cd pinchana-inst
uv run pytest -q
PINCHANA_INST_LIVE=1 uv run pytest -q
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

`VERSION` is the single source of truth for the rolling product release. It uses
strict CalVer in `YY.MM.ITERATION` form. Releases within a month increment the
last number (`26.08.1`, `26.08.2`); the first release of a new month resets it to
`1`. The version tool calculates that transition, converts the result to PEP 440,
and keeps every Python submodule manifest and lockfile synchronized:

```bash
python scripts/version.py check
python scripts/version.py next
python scripts/version.py bump
```

Because the Python projects are separate Git submodules, commit and push their
generated `pyproject.toml` and `uv.lock` changes first. Then commit their updated
pointers together with `VERSION` in this repository. After the main build is
green, create an annotated tag matching `VERSION` exactly:

```bash
git tag -a v26.08.1 -m "Release 26.08.1"
git push origin v26.08.1
```

`python scripts/version.py set YY.MM.N` remains available for an explicit
correction. CI rejects mismatched or nonstandard release tags. Image tag policy:

- Push to `main`: publishes the snapshot channel `latest`; build metadata reports
  `<VERSION>+dev.<commit>`.
- Release tag such as `v26.08.1`: publishes immutable `26.08.1`, rolling monthly
  `26.08`, and rolling release channel `stable`.
- Manual workflow dispatch can select services but cannot mint release tags.

The legacy `stable` branch is not a release input. This prevents manual builds
and branch drift from overwriting the rolling release channel.

On a deployment host, apply the newest release only through the rolling updater:

```bash
python scripts/update_rolling.py --env-file .env --dry-run
python scripts/update_rolling.py --env-file .env
# Include DLP only when that profile should advance with the API release:
python scripts/update_rolling.py --env-file .env --dlp
```

When the Gluetun digest changes, recreate it before applying the rest of the
stack; never use `docker restart gluetun`:

```bash
docker compose --env-file .env up --detach --force-recreate gluetun
docker compose --env-file .env up --detach
```

## Adding a Module

Adding a service requires coordinated changes:

1. Add a new `pinchana-<name>` submodule with `src/pinchana_<name>/main.py`.
2. Add routing and container metadata in `config/modules.yaml`.
3. Add services to `docker-compose.yml` and `docker-compose.dev.yml`.
4. Add ports, endpoints, and container names to `.env.example`.
5. Add workflow detection and Dockerfile mapping in `.github/workflows/docker-publish.yml`.

## License

MIT. See `LICENSE`.
