# Pinchana API

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![Publish Docker images](https://github.com/Pinchana/pinchana-api/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Pinchana/pinchana-api/actions/workflows/docker-publish.yml)

Pinchana API is a Docker Compose-based media extraction gateway. A central FastAPI server accepts the versioned `/v1/scrape` request, selects a platform module, and returns a normalized response. The production stack routes outbound scraper traffic through Gluetun; the development stack can run without VPN credentials. The unversioned `/scrape` route remains available for existing integrations.

## Supported modules

| Module | Routes |
| --- | --- |
| TikTok | `tiktok.com`, `vm.tiktok.com`, `vt.tiktok.com`, `tt.site` |
| Instagram | `instagram.com`, `instagr.am` |
| YouTube Shorts | `youtube.com/shorts` |
| SoundCloud | `soundcloud.com`, `on.soundcloud.com` |
| YouTube Music | `music.youtube.com` |
| Apple Music | `music.apple.com` (individual tracks only) |
| Spotify | `open.spotify.com` |
| Deezer | `deezer.com` and Deezer share links |
| Threads | `threads.net`, `threads.com` |
| X / Twitter | `x.com`, `twitter.com`, `vxtwitter.com`, `fxtwitter.com` |
| Coub | `coub.com/view`, `coub.com/embed` |
| Bluesky | `bsky.app/profile/<handle-or-did>/post/<id>` |

All 12 scrapers are installed into the gateway image at build time. The gateway
calls their Python handlers directly and serves the API and cached media on
port `8080`. Production uses Gluetun for egress. Gluetun's authenticated control
port defaults to `8000` on loopback. The optional DLP stack has its own internal
network and isolated workers for private downloads.

Bluesky returns public post text, photos, MP4 video, and one level of quotes.
`/v1/inspect` returns post and quote metadata without downloading media.

Threads uses its HTTP extractor first. The browser fallback uses the free,
keyless CloakBrowser Chromium 146 release. Leave `CLOAKBROWSER_LICENSE_KEY`
unset. The gateway downloads the browser from CloakBrowser on first use, and
Compose keeps it in the `threads-browser` volume across upgrades.

## Repository layout

The repository contains Compose configuration, release tooling, and the
`pinchana-*` module directories. Each Python package has its own
`pyproject.toml`, `uv.lock`, and source directory. The gateway locks and
installs those packages together.

`pinchana-core` contains shared models, storage, music helpers, and Gluetun
control logic.

## Quick start

```bash
git clone https://github.com/Pinchana/pinchana-api.git
cd pinchana-api
```

If you already have a checkout with initialized submodules, save any module
changes and back up local files inside those directories that you need to keep.
Run these commands before pulling the migration:

```bash
git submodule deinit --all
git -c submodule.recurse=false pull --ff-only
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
default it updates the gateway image and Gluetun. Add `--dlp` to
include all three DLP images and its dedicated Gluetun image; without that flag,
DLP values are untouched.

When upgrading from the per-scraper Compose stack, pin the first release with
the bundled gateway, then recreate the stack with `--remove-orphans` to remove
the old scraper containers. If this Compose project already runs DLP, include
`--profile dlp` when applying the update. The shared `scraper-cache` volume is
reused.

Build the gateway from source without a VPN:

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

The same endpoint accepts supported TikTok, YouTube Shorts, SoundCloud, YouTube Music, Spotify, Deezer, Threads, Twitter/X, Bluesky, Coub, and Instagram URLs. Configure independently revocable machine keys with `PINCHANA_API_KEYS`, a JSON object such as `{"bot":"secret","automation":"other-secret"}`. Machine requests to `/v1/scrape`, legacy `/scrape`, `/media/...`, and `/admin/...` must include `X-API-Key`.

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

In production, the gateway uses Gluetun's network namespace:

```yaml
network_mode: container:gluetun
```

Gluetun publishes the gateway listener. Development Compose publishes the same
listener directly and sets `VPN_ENABLED=false`.

Never run `docker restart gluetun`; it can clear VPN credentials and cause `AUTH_ERROR`. Recreate it instead:

```bash
docker compose --env-file .env up --detach --force-recreate gluetun
```

Shorts can use YouTube cookies from `SHORTS_COOKIES_DIR` mounted read-only to `/run/pinchana-cookies`. `SHORTS_MAX_MB_PER_MINUTE` controls optional MP4 re-encoding for oversized output.

## Development

Run all scrapers in the gateway locally:

```bash
cd pinchana-server
uv sync --locked
VPN_ENABLED=false uv run uvicorn pinchana_server.main:app --reload
```

Run Instagram tests:

```bash
cd pinchana-inst
uv run pytest -q
PINCHANA_INST_LIVE=1 uv run pytest -q
```

Docker builds must use the repo root as build context:

```bash
docker build -f pinchana-server/Dockerfile -t pinchana-server .
```

## Releases and Images

The gateway and optional DLP images are published to:

```text
ghcr.io/pinchana/pinchana-api/<server|dlp-api|dlp-orchestrator|dlp-worker>:<tag>
```

`VERSION` is the single source of truth for the rolling product release. It uses
strict CalVer in `YY.MM.ITERATION` form. Releases within a month increment the
last number (`26.08.1`, `26.08.2`); the first release of a new month resets it to
`1`. The version tool calculates that transition, converts the result to PEP 440,
and keeps every Python package manifest and lockfile synchronized:

```bash
python scripts/version.py check
python scripts/version.py next
python scripts/version.py bump
```

`bump` commits the package metadata and lockfiles together with `VERSION` and
pushes the current branch. After the main build is green, create an annotated
tag matching `VERSION` exactly:

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

1. Add a package under `pinchana-<name>/` that registers a `ScraperPlugin` with
   its URL patterns and handlers. Use `pinchana-bluesky/` as a reference.
2. Add the package and its local path to `pinchana-server/pyproject.toml`. Add it
   to the module list in `pinchana_server/modules.py`, then refresh the gateway
   lockfile with `uv lock --project pinchana-server`.
3. Build the gateway image and test the relevant public and authenticated API
   routes. The existing gateway port, media cache, and deployment cover new
   modules.

## License

MIT. See `LICENSE`.

Apple Music uses the `pinchana-apple-music/` package inside the gateway.
Configure `SOCIALCRAWL_API_KEY`
for metadata lookup; audio is matched and downloaded through YouTube Music.
Only individual tracks are accepted, including album URLs with a selected
`?i=TRACK_ID`. See [the module guide](pinchana-apple-music/README.md).

Python dependencies and build backends were refreshed across all API packages,
including the DLP requirements files. The Threads module's `pyee` version is
limited by Playwright's declared `pyee<15` requirement. Refresh each package's
lockfile with `uv lock --upgrade` and install it with `uv sync --frozen`.

### Host cookies for full YouTube video sessions

DLP accepts full YouTube video URLs only. Apple Music, Spotify, YouTube Music,
Shorts and playlist pages remain on their own service routes. Starting Compose
with `--profile dlp` also starts the gateway, which handles these scrapers.

To supply optional operator cookies, put a Netscape cookie file at
`<DLP_HOST_COOKIES_DIR>/youtube.txt`. The default directory is
`./secrets/dlp-cookies`, which is ignored by Git. The DLP API mounts it read-only
at `/run/host-cookies`, runs as UID/GID 10001, and must be able to read the file:

```sh
sudo install -d -o 10001 -g 10001 -m 700 secrets/dlp-cookies
sudo install -o 10001 -g 10001 -m 600 /path/to/cookies.txt secrets/dlp-cookies/youtube.txt
```

Host cookies are optional. Without the file, downloads remain anonymous unless
the client submits user cookies. For each submission without `cookiesEnc`, the
DLP API encrypts host cookies for the allocated worker before queuing anything
in Redis. User cookies always take priority. Send `useHostCookies: false` in a
job submission to disable the host fallback for that session. Host cookies are
never returned to clients. The worker's existing temporary-cookie cleanup also
applies to these envelopes. Restart/recreate `dlp-api` after changing the mount
configuration; replacing `youtube.txt` within the directory is read on the next
submission.
