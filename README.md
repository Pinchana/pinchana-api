# Pinchana API

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)
[![Publish Docker images](https://github.com/Pinchana/pinchana-api/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Pinchana/pinchana-api/actions/workflows/docker-publish.yml)

Pinchana extracts media and metadata from 13 scraper integrations. Use
`pinchana-scraper` in a Python script, or run the FastAPI gateway to serve
scrape requests and cached media over HTTP.

[Python API](#python-api) · [Docker gateway](#run-the-http-gateway) · [Supported modules](#supported-modules) · [Development](#development)

## Get the source

```sh
git clone https://github.com/Pinchana/pinchana-api.git
cd pinchana-api
```

## Python API

The `pinchana-scraper` bundle gives you one import namespace for all 13
scrapers. Python loads each scraper when you import it. You can also install
individual scraper packages. [Bundle guide](pinchana-scraper/README.md)

Save this as `example.py` and replace `VIDEO_ID` with a YouTube Shorts ID.

```python
import asyncio

from pinchana_scraper import shorts


async def main():
    result = await shorts.scrape(
        "https://www.youtube.com/shorts/VIDEO_ID",
        cache_dir="./downloads",
    )
    print(result.caption)
    print(result.media_path(result.video_url))


asyncio.run(main())
```

Run it from the repository root with Python 3.13+ and `uv`. Set
`VPN_ENABLED=false` before importing a scraper when running outside Gluetun.

```sh
VPN_ENABLED=false uv run --project pinchana-scraper --locked python example.py
```

- Use `from pinchana_scraper.shorts import scrape` to import the function directly.
- `scrape()` returns metadata and downloads media into the cache. Pass a returned media URL to `result.media_path()` to find the local file, including carousel and quote attachments.
- Catch `pinchana_core.ScrapeError` for scraper failures. It exposes `status_code` and `detail`.
- Use one event loop for concurrent calls to a scraper. Check each module guide for platform credentials and local tool requirements.

| Operation | Available in |
| --- | --- |
| `scrape(url, *, cache_dir=None)` | All scrapers |
| `inspect(url)` for metadata | Bluesky, Coub, Threads, X / Twitter |
| `playlist(url)` for ordered track URLs | Deezer, Spotify |
| `scrape_playlist_item(url)` for one YouTube video | Shorts |

## Run the HTTP gateway

A single FastAPI process calls the bundled scrapers directly. The gateway
serves the API and cached media on port `8080` by default.

For a new checkout, copy the sample configuration and replace the placeholder in
`PINCHANA_API_KEYS`. Give each machine client its own named key so you can
revoke it independently. [Configuration example](.env.example)

```sh
cp .env.example .env
chmod 600 .env
```

```dotenv
PINCHANA_API_KEYS={"automation":"REPLACE_WITH_LONG_RANDOM_MACHINE_KEY"}
```

### Development with Docker

Build the gateway from the checkout. This Compose file runs the gateway
without a VPN.

```sh
docker compose --env-file .env -f docker-compose.dev.yml up --detach --build
```

### Production with Docker

Configure the VPN in `.env`. For NordVPN OpenVPN, use the service username and
password from Nord Account's Manual setup page. Providers that issue manual
WireGuard keys can use `VPN_TYPE=wireguard` and `WIREGUARD_PRIVATE_KEY`.

```dotenv
VPN_SERVICE_PROVIDER=nordvpn
VPN_TYPE=openvpn
OPENVPN_PROTOCOL=tcp
OPENVPN_USER=REPLACE_WITH_NORDVPN_SERVICE_USERNAME
OPENVPN_PASSWORD=REPLACE_WITH_NORDVPN_SERVICE_PASSWORD
```

Use the rolling updater to pin the production images by digest, then start the
stack. Gluetun publishes the gateway listener and provides VPN egress.

```sh
python scripts/update_rolling.py --env-file .env
docker compose --env-file .env config --quiet
docker compose --env-file .env up --detach
```

Use the same updater for upgrades. Recreate Gluetun through Compose when its
digest changes so it reloads VPN credentials. [Docker operations guide](DOCKER.md)

### Check the gateway

```sh
curl --fail-with-body --silent --show-error http://localhost:8080/health
```

## API usage

Send the target URL to `POST /v1/scrape` with your machine key.

```sh
curl --fail-with-body --silent --show-error \
  http://localhost:8080/v1/scrape \
  --header 'Content-Type: application/json' \
  --header 'X-API-Key: REPLACE_WITH_MACHINE_KEY' \
  --data '{"url":"https://www.youtube.com/shorts/VIDEO_ID"}'
```

The response contains `data` and `meta`. Read downloads from the ordered
`data.media` list. Images and videos include dimensions when the gateway can
probe the cached file. V1 errors include an `error` object with a stable
`code` and `message`.

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/scrape` | Download media and return normalized metadata |
| `POST /v1/inspect` | Inspect supported posts and quote metadata without downloading media |
| `GET /media/…` | Fetch a cached file with the machine key |
| `POST /v1/bot/ytgroups` | Prepare a full YouTube video for a Telegram upload |
| `POST /scrape` | Return the legacy flat response |

Machine routes use `X-API-Key`. The OpenAPI reference is available at
`/docs` on the running gateway. [Telegram cache behavior](docs/TELEGRAM_MEDIA_CACHE.md)

### Browser and mobile clients

| Client | Authentication | Scrape endpoint |
| --- | --- | --- |
| Browser | `POST /web/verify` exchanges a Turnstile token for a bearer session | `POST /v1/web/scrape` |
| Mobile | Use scoped installation tokens. Set `MOBILE_AUTH_REQUIRED=true` to require them for ordinary scrapes. | `POST /v1/mobile/scrape` |

Browser and mobile sessions use `/web/media/…` and `/mobile/media/…`,
respectively. Check sessions with `GET /web/session` or `GET /v1/mobile/session`.
Configure Turnstile with `TURNSTILE_SECRET_KEY`,
`TURNSTILE_EXPECTED_HOSTNAME`, `TURNSTILE_EXPECTED_ACTION=turnstile-spin-v1`,
and `TURNSTILE_SESSION_SECRET`. The shipped mobile configuration uses
`MOBILE_AUTH_MODE=guest`. [Instance certificates](docs/INSTANCE_TRUST.md) · [Mobile installation authentication](docs/MOBILE_AUTH.md)

### Private YouTube downloads

The optional DLP profile handles full YouTube video downloads in isolated
workers. Mobile DLP always requires an authenticated installation. Keep
`DLP_ENABLED=false` until the production preflight and canary pass.
[DLP rollout guide](docs/DLP_PRODUCTION_ROLLOUT.md)

| Cookie use | Compose setting | Default host location |
| --- | --- | --- |
| Shorts and YouTube group uploads | `SHORTS_COOKIES_DIR` | `./secrets/yt-cookies/` |
| DLP fallback for full videos | `DLP_HOST_COOKIES_DIR` | `./secrets/dlp-cookies/youtube.txt` |

Compose mounts both directories read-only. Use a Netscape cookie file from an
account that can play the requested video. DLP uses client-submitted cookies
first when present. [Shorts cookies](scrapers/pinchana-shorts/README.md#configuration) · [DLP host cookies](pinchana-dlp/README.md#optional-host-cookies)

### Administration

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Check gateway and scraper health |
| `GET /admin/modules` | List loaded scrapers and URL patterns |
| `GET /admin/vpn/status` | Check the VPN |
| `POST /admin/vpn/rotate` | Request a VPN reconnect |

## Supported modules

| Scraper | Python import from `pinchana_scraper` | Typical URLs |
| --- | --- | --- |
| [Apple Music](scrapers/pinchana-apple-music/README.md) | `apple_music` | `music.apple.com`, individual tracks |
| [Bluesky](scrapers/pinchana-bluesky/README.md) | `bluesky` | `bsky.app/profile/<handle-or-did>/post/<id>` |
| [Coub](scrapers/pinchana-coub/README.md) | `coub` | `coub.com/view/…`, `coub.com/embed/…` |
| [Deezer](scrapers/pinchana-deezer/README.md) | `deezer` | `deezer.com` and Deezer share links |
| [Instagram](scrapers/pinchana-inst/README.md) | `instagram` | `instagram.com`, `instagr.am` |
| [SoundCloud](scrapers/pinchana-soundcloud/README.md) | `soundcloud` | `soundcloud.com`, `on.soundcloud.com` |
| [Spotify](scrapers/pinchana-spotify/README.md) | `spotify` | `open.spotify.com` |
| [Threads](scrapers/pinchana-threads/README.md) | `threads` | `threads.net`, `threads.com` |
| [TikTok](scrapers/pinchana-tiktok/README.md) | `tiktok` | `tiktok.com`, `vm.tiktok.com`, `vt.tiktok.com`, `tt.site` |
| [X / Twitter](scrapers/pinchana-twitter/README.md) | `twitter` | `x.com`, `twitter.com`, share links via the gateway |
| [YouTube groups](scrapers/pinchana-ytgroups/README.md) | `ytgroups` | `youtube.com/watch`, `youtu.be` via the Telegram gateway endpoint |
| [YouTube Music](scrapers/pinchana-ytmusic/README.md) | `ytmusic` | `music.youtube.com` |
| [YouTube Shorts](scrapers/pinchana-shorts/README.md) | `shorts` | `youtube.com/shorts/…` |

## Development

| Path | Responsibility |
| --- | --- |
| `pinchana-core/` | Shared models, caching, music helpers, and Gluetun control |
| `pinchana-scraper/` | Python bundle and scraper imports |
| `pinchana-server/` | FastAPI gateway, authentication, and HTTP response handling |
| `scrapers/` | Platform scraper packages |
| `pinchana-dlp/` | Optional private download services and workers |
| `docs/` | Deployment, client auth, and release guides |

Run the gateway directly or run its test suite from the repository root.

```sh
VPN_ENABLED=false uv run --project pinchana-server --locked \
  uvicorn pinchana_server.main:app --reload

uv run --project pinchana-server --locked pytest -q pinchana-server/tests
```

To add a scraper under `scrapers/`, follow the Bluesky package for plugin
registration. Add it to the gateway's module list and Python dependencies, then expose
its Python functions through the bundle. Refresh both lockfiles and test both entry
points. [Bluesky package](scrapers/pinchana-bluesky/) · [Gateway module list](pinchana-server/src/pinchana_server/modules.py) · [Bundle sources](pinchana-scraper/src/pinchana_scraper/)

<details>
<summary>Update a checkout that still uses Git submodules</summary>

Back up any module edits or local files you need before deinitializing the
old submodules.

```sh
git submodule deinit --all
git -c submodule.recurse=false pull --ff-only
```

For a stack that still has a container per scraper, follow the first-upgrade
instructions in the [Docker guide](DOCKER.md).

</details>

## Releases

`VERSION` uses `YY.MM.ITERATION`. The release script keeps Python package
versions and lockfiles in sync.

| Channel | GHCR tags |
| --- | --- |
| Main branch snapshot | `latest` |
| Tagged release | An exact version such as `26.11.14`, monthly `26.11`, and `stable` |

Images live under `ghcr.io/pinchana/pinchana-api/`. See the release guide for
building, publishing, and verifying a tagged release.
[Release guide](docs/RELEASING.md)

## License

Pinchana is released under the MIT License. [License text](LICENSE)
