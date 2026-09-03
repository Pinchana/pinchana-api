# DLP production rollout

The DLP stack is deployed in two phases. Infrastructure is brought up while the public capability remains disabled; `pinchana-server` advertises protocol v2 only after the feature flag is enabled and the internal DLP health check succeeds.

## 1. Publish immutable artifacts

Publish the `pinchana-dlp` and `pinchana-server` commits first, then commit and publish their pointers from `pinchana-api`. Publish the web application separately. Do not point the parent repository at submodule commits that are not reachable from their public remotes.

Use the Docker publishing workflow to create all three DLP images. On the production host, update the APIs and DLP images as one coherent release and atomically replace their `.env` values with immutable repository digests:

```bash
python3 scripts/update_rolling.py --env-file .env --dlp --dry-run
python3 scripts/update_rolling.py --env-file .env --dlp
```

The updater resolves the repository already configured for each service, discovers the newest released CalVer through `stable`, verifies that every selected API and DLP image reports the same release, and pins all selected images by digest. Gluetun is resolved independently because it does not carry Pinchana CalVer labels. It writes nothing until all selected digests resolve successfully. `--dlp` is required to touch `DLP_API_IMAGE`, `DLP_ORCHESTRATOR_IMAGE`, `DLP_WORKER_IMAGE`, or `DLP_VPN_IMAGE`.

The resulting production values are immutable:

```env
DLP_API_IMAGE=ghcr.io/pinchana/pinchana-api/dlp-api@sha256:...
DLP_ORCHESTRATOR_IMAGE=ghcr.io/pinchana/pinchana-api/dlp-orchestrator@sha256:...
DLP_WORKER_IMAGE=ghcr.io/pinchana/pinchana-api/dlp-worker@sha256:...
DLP_VPN_IMAGE=qmcgaw/gluetun@sha256:...
DLP_DOH_URL=https://cloudflare-dns.com/dns-query
```

## 2. Prepare secrets and storage

Generate three distinct random values of at least 32 characters for `DLP_GATEWAY_TOKEN`, `DLP_OWNER_SECRET`, and `DLP_REDIS_PASSWORD`. Keep `DLP_ENABLED=false`. Preserve the existing production Turnstile and VPN secrets.

Create the temporary job root on the Docker host. It must not be a symlink or world-writable. Job directories are created as UID/GID `10001` with mode `0700`, shared only by the ephemeral worker and read-only DLP API mount.

```bash
sudo install -d -o root -g root -m 0711 /srv/pinchana-dlp/jobs
```

Downloads are temporary. Do not back up or synchronize this directory.

## 3. Pull and preflight

```bash
docker compose --env-file .env --profile dlp pull dlp-redis dlp-vpn
python scripts/dlp-prod-preflight.py --env-file .env --phase infra
```

The preflight rejects placeholder or reused secrets, `latest` image tags, unsafe job-directory permissions, missing local images, published DLP ports, non-internal worker networks, direct DNS resolution outside the DLP VPN, Docker-socket exposure outside the orchestrator, and an incorrectly enabled feature flag.

## 4. Start infrastructure with capability disabled

```bash
docker compose --env-file .env --profile dlp up --detach \
  dlp-redis dlp-vpn dlp-api dlp-orchestrator
docker compose --env-file .env --profile dlp ps
docker compose --env-file .env --profile dlp logs --tail=100 dlp-api dlp-orchestrator dlp-vpn
```

All four services must report healthy. Confirm that Redis and the worker networks have no host ports and that no worker exists before allocation:

```bash
docker ps --filter label=pinchana.dlp.job
```

Deploy the web application with production values for `PINCHANA_API_URL`, `NEXT_PUBLIC_TURNSTILE_SITE_KEY`, and `PINCHANA_INSTANCE_PUBLIC_KEY`. While the flag is false, `/web/capabilities` must report DLP unavailable and the web controls remain disabled.

## 5. Canary and enable

Use a non-public canary instance with the same images and networking for one anonymous YouTube download and one explicitly selected cookie profile. Check that the worker is removed, its job directory expires, and the plaintext cookie marker is absent from gateway, API, Redis, and orchestrator logs.

After the canary succeeds, change only `DLP_ENABLED=true`, recreate the gateway, and run the enable-phase preflight:

```bash
docker compose --env-file .env up --detach --no-deps --force-recreate server
python scripts/dlp-prod-preflight.py --env-file .env --phase enable
```

Verify through an authenticated web session that `/web/capabilities` reports `available: true` and `protocol: 2`. Then repeat an anonymous YouTube smoke test on production before announcing availability.

Monitor DLP allocation latency, active-job count, worker duration, output bytes, failure rate, Redis health, VPN health, host disk usage, and orphaned containers/directories. Never log request bodies or cookie envelopes.

## Rollback

Set `DLP_ENABLED=false` and recreate only `server`. This immediately removes the advertised capability without interrupting existing scraper modules:

```bash
docker compose --env-file .env up --detach --no-deps --force-recreate server
```

Allow active jobs to finish or expire. Then stop the profile if necessary:

```bash
docker compose --env-file .env --profile dlp stop dlp-orchestrator dlp-api dlp-vpn dlp-redis
```

Do not delete the job root until no `pinchana.dlp.job` containers remain. Retain no Redis or job-directory backup.
