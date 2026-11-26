# Docker workflows

Run commands from the repository root so the gateway image can install the bundled scraper packages.

## Production images

```sh
cp .env.example .env
chmod 600 .env
# Replace every required placeholder before continuing.
docker compose --env-file .env config --quiet
python scripts/update_rolling.py --env-file .env
docker compose --env-file .env up --detach
docker compose --env-file .env ps
```

On the first update from the multi-container scraper stack, add

`--remove-orphans` to `up` after pinning a release with bundled scrapers. Include
`--profile dlp` if that project already runs DLP. The existing media volume is
reused.

The rolling updater pins Pinchana release images and the main Gluetun image
from the `latest` development channel by digest. With `--dlp`, it pins the
dedicated DLP Gluetun image from the stable `v3` channel.
Gluetun uses its encrypted DNS proxy with Cloudflare only; Compose supplies
`1.1.1.1` and `1.0.0.1` for bootstrap and health fallback. Google resolvers are
not used. Its authenticated control API binds to `127.0.0.1` on the Docker host
by default. The gateway accesses it through the shared namespace.

## Automatic stable updates

On a host that runs the gateway and DLP profile, schedule
`scripts/deploy_stable.py` under the user that manages the Docker stack. Use
the absolute path to the script in the deployed checkout. For example, add
this entry with `crontab -e`.

```cron
*/5 * * * * /usr/bin/timeout 20m /usr/bin/python3 -Bu /path/to/pinchana-api/scripts/deploy_stable.py 2>&1 | /usr/bin/logger -t pinchana-stable
```

The updater waits for a published stable GitHub Release and its successful
Docker workflow. It pulls the exact gateway, DLP API, orchestrator, and worker
images, verifies their version labels, and pins them by digest. Active DLP
workers defer the update to the next check. A failed rollout restores the
previous image pins and checks gateway health again. It waits 30 minutes
before retrying a release that rolled back.

View the host's update history with `journalctl -t pinchana-stable`. The
updater uses the host's existing Compose file and configuration. It keeps its
private rollback state under `~/.local/state/pinchana-stable` by default.

## Local source build

```sh
docker compose --env-file .env -f docker-compose.dev.yml \
  up --detach --build
```

Build the gateway image explicitly:

```sh
docker build --file pinchana-server/Dockerfile --tag pinchana-server:local .
```

Do not run `docker restart gluetun`. Recreate it through Compose so that VPN credentials and dependent network namespaces are initialized correctly:

```sh
docker compose --env-file .env up --detach --force-recreate gluetun
docker compose --env-file .env up --detach
```
