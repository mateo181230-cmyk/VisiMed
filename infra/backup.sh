#!/bin/sh
set -eu
umask 077
cd /opt/uno-visitas/current
destination="/opt/uno-visitas/backups/uno-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose --env-file /opt/uno-visitas/runtime.env -f infra/docker-compose.prod.yml exec -T postgres pg_dump -U uno -d uno -Fc > "$destination"
docker compose --env-file /opt/uno-visitas/runtime.env -f infra/docker-compose.prod.yml exec -T postgres pg_restore --list < "$destination" >/dev/null
printf 'Backup verified: %s\n' "$destination"
