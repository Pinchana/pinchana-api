# Docker workflows

Run commands from the repository root because module Dockerfiles copy both `pinchana-core` and the selected service.

## Production images

```sh
cp .env.example .env
chmod 600 .env
# Replace every required placeholder before continuing.
docker compose --env-file .env config --quiet
docker compose --env-file .env pull
docker compose --env-file .env up --detach
docker compose --env-file .env ps
```

The rolling updater pins both Pinchana release images and Gluetun's stable `v3`
channel by digest. It deliberately does not consume Gluetun's edge `latest` tag.
Gluetun uses its encrypted DNS proxy with Cloudflare only; Compose supplies
`1.1.1.1` and `1.0.0.1` for bootstrap and health fallback. Google resolvers are
not used. Its authenticated control API binds to `127.0.0.1` on the Docker host
by default; scraper services access it privately through the shared namespace.

## Local source build

```sh
docker compose --env-file .env -f docker-compose.dev.yml \
  up --detach --build
```

Build one module explicitly:

```sh
docker build --file pinchana-inst/Dockerfile --tag pinchana-inst:local .
```

Do not run `docker restart gluetun`. Recreate it through Compose so that VPN credentials and dependent network namespaces are initialized correctly:

```sh
docker compose --env-file .env up --detach --force-recreate gluetun
docker compose --env-file .env up --detach
```
