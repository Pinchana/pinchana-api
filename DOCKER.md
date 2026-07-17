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
