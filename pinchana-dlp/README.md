# Pinchana DLP

Pinchana DLP is the internal, asynchronous download service used by the Pinchana web gateway. It is not a `/scrape` plugin and is never exposed directly to browsers.

## Protocol v2

The trusted gateway authenticates with `x-dlp-service-token` and supplies an opaque `x-job-owner` derived from its signed web session. A job allocation returns a short-lived X25519 worker public key. The browser may then submit an AES-256-GCM cookie envelope containing:

- `version`, `keyId`, and the client X25519 public key;
- an independent 32-byte HKDF salt;
- a 12-byte AES-GCM IV; and
- ciphertext authenticated with `pinchana-dlp:v2:{jobId}:{keyId}`.

Anonymous submissions omit `cookiesEnc`; the worker runs yt-dlp without `--cookies`. DLP accepts YouTube hosts only. Quality, video codec, container, audio format/bitrate, better-audio preference, dubbed language, subtitle language, and filename style are validated fixed options; callers cannot provide a yt-dlp format string or output template. Codec and dubbed-track selection fall back safely, selected subtitles prefer creator captions with automatic captions as fallback, explicit video containers are remuxed without transcoding, and audio conversion is handled by the pinned worker FFmpeg. Completed files use one of the advertised branded filename styles and always retain `[pinchana.cc]`.

Gateway routes:

- `POST /v2/jobs`
- `POST /v2/jobs/{jobId}/submit`
- `GET /v2/jobs/{jobId}`
- `GET /v2/jobs/{jobId}/file`

Worker routes under `/internal/jobs/...` require a unique credential for that job. Redis and all DLP routes are intended for internal networks only.

## Runtime boundaries

- `api`: validates service authentication, ownership, state, URL, limits, and ciphertext. It has no Docker socket.
- `orchestrator`: is the only component with the Docker socket. It creates one hardened worker per job.
- `worker`: holds the X25519 private key and briefly decrypts cookies into `/run/cookies`, a RAM-backed mount.
- `redis`: contains job metadata and ciphertext only.

Workers use a read-only root filesystem, dropped capabilities, `no-new-privileges`, PID/CPU/memory limits, an output-only job mount, RAM-backed temporary directories, a forced lifetime, and automatic container removal. yt-dlp and Deno are pinned in the worker image; executable components are not downloaded at runtime.

The official defaults allow three concurrent workers, an 8 GiB final artifact, and 45 minutes of execution within a two-hour job lifetime. During format merging, the worker permits temporary files up to twice the final limit plus 512 MiB, while the completed artifact is still rejected above 8 GiB. Size and concurrency remain configurable for self-hosted deployments.

## Development

The standalone Compose stack is for component development. Production uses the `dlp` profile from the `pinchana-api` repository so the gateway, image pins, private networks, and feature flag are validated together.

Copy `example.env` to `.env`, protect it, replace every secret and absolute host path, and validate the rendered configuration before starting services:

```sh
cp example.env .env
chmod 600 .env
docker compose --env-file .env --profile build config --quiet
docker compose --env-file .env --profile build build worker-image
docker compose --env-file .env up --detach --build redis dlp-api vpn orchestrator
docker compose --env-file .env ps
```

Run protocol tests, including the Node WebCrypto to Python cross-language vector:

```sh
uv run --with-requirements requirements-test.txt pytest -q
```

Production rollout is intentionally gated by `DLP_ENABLED=false` in `pinchana-server`. Build and deploy capacity first, then enable the gateway capability after health checks and a gated live smoke test.

## Optional host cookies

Mount an operator-owned directory containing `youtube.txt` (Netscape format,
maximum 256 KiB) into the API container at `/run/host-cookies:ro`. Compose uses
`DLP_HOST_COOKIES_DIR`, defaulting to `./secrets/dlp-cookies`; inside the API,
`DLP_HOST_COOKIES_FILE=/run/host-cookies/youtube.txt`. UID/GID 10001 must be able to
read it. Keep the directory out of Git and images. For example:

```sh
sudo install -d -o 10001 -g 10001 -m 700 secrets/dlp-cookies
sudo install -o 10001 -g 10001 -m 600 /path/to/cookies.txt secrets/dlp-cookies/youtube.txt
```

A missing file means no host fallback. Valid host cookies are encrypted for the
allocated worker with the same protocol-v2 X25519/HKDF/AES-GCM envelope used for
client cookies; Redis only receives ciphertext. `cookiesEnc` from the client
always takes priority. `useHostCookies: false` disables host cookies for an
individual job/session. The health capabilities expose only
`hostCookiesAvailable`, never file contents. Cookie file parsing/encryption errors
abort submission before queuing and return a generic error.

DLP accepts full YouTube videos only. `music.youtube.com`, Apple Music, Shorts,
channel URLs and playlist pages are rejected. Audio extraction from a full
YouTube video is still an available output format; music-platform downloads use
the dedicated scraper services.
