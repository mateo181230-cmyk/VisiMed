#!/bin/sh
# Configuración/activación y restauración: docs/operaciones/respaldos.md
set -eu
umask 077

backup_env=${UNO_BACKUP_ENV_FILE:-/etc/uno-visitas/backup.env}
if [ -f "$backup_env" ]; then
    set -a
    # Archivo de shell propiedad de root; nunca se carga el .env de la aplicación como código.
    . "$backup_env"
    set +a
fi

app_dir=${UNO_BACKUP_APP_DIR:-/opt/uno-visitas/current}
backup_dir=${UNO_BACKUP_DIR:-/opt/uno-visitas/backups}
runtime_env=${UNO_RUNTIME_ENV_FILE:-/opt/uno-visitas/runtime.env}
compose_file=${UNO_BACKUP_COMPOSE_FILE:-$app_dir/infra/docker-compose.prod.yml}
offsite=${UNO_BACKUP_OFFSITE:-0}
local_days=${UNO_BACKUP_LOCAL_DAYS:-14}
daily=${UNO_BACKUP_KEEP_DAILY:-7}
weekly=${UNO_BACKUP_KEEP_WEEKLY:-4}
monthly=${UNO_BACKUP_KEEP_MONTHLY:-6}
backup_host=${UNO_BACKUP_HOST:-uno-visitas}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
for value in "$local_days" "$daily" "$weekly" "$monthly"; do
    case "$value" in ''|*[!0-9]*) fail 'La retención exige enteros positivos' ;; esac
    [ "$value" -gt 0 ] || fail 'La retención exige enteros positivos'
done
case "$offsite" in 0|1) ;; *) fail 'UNO_BACKUP_OFFSITE debe ser 0 o 1' ;; esac
case "$backup_dir" in /*) ;; *) fail 'UNO_BACKUP_DIR debe ser absoluta' ;; esac
[ -r "$runtime_env" ] || fail 'No se puede leer UNO_RUNTIME_ENV_FILE'
[ -r "$compose_file" ] || fail 'No se puede leer el compose de UNO'
command -v docker >/dev/null || fail 'Falta docker'
command -v flock >/dev/null || fail 'Falta flock (util-linux)'

mkdir -p "$backup_dir"
backup_dir=$(cd "$backup_dir" && pwd -P)
exec 9>"$backup_dir/.backup.lock"
flock -n 9 || fail 'Ya hay otro respaldo de UNO en ejecución'

partial=''
destination=''
finish() {
    status=$?
    trap - EXIT
    if [ "$status" -ne 0 ]; then
        printf 'El respaldo falló; no se aplicó retención local. Revisar el servicio.\n' >&2
        [ -z "$partial" ] || printf 'Archivo parcial conservado: %s\n' "$partial" >&2
        [ -z "$destination" ] || printf 'Dump local conservado: %s\n' "$destination" >&2
    fi
    exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Compose necesita interpolar las imágenes aunque exec solo use el postgres existente.
export UNO_RELEASE_ID=${UNO_RELEASE_ID:-backup}
export UNO_RUNTIME_ENV_FILE="$runtime_env"
compose() {
    docker compose --project-name uno-visitas --env-file "$runtime_env" -f "$compose_file" "$@"
}

partial=$(mktemp "$backup_dir/.uno-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX.dump.partial")
compose exec -T postgres pg_dump -U uno -d uno -Fc > "$partial"
[ -s "$partial" ] || fail 'pg_dump produjo un archivo vacío'
compose exec -T postgres pg_restore --list < "$partial" >/dev/null
# Recorre/descomprime todo el archivo, no solo el índice. No ejecuta SQL en la base.
compose exec -T postgres pg_restore --file=/dev/null < "$partial"
destination="$backup_dir/$(basename "$partial" .partial | sed 's/^\.//')"
mv "$partial" "$destination"
partial=''
printf 'Dump local validado estructuralmente: %s\n' "$destination"

if [ "$offsite" = 1 ]; then
    command -v restic >/dev/null || fail 'Falta restic; se conserva el dump local'
    [ -n "${RESTIC_REPOSITORY:-}" ] || fail 'Define RESTIC_REPOSITORY fuera del VPS'
    # Impide activar el modo externo con una ruta local o un backend HTTP sin TLS.
    case "$RESTIC_REPOSITORY" in
        s3:https://*|sftp:*|rest:https://*|b2:*|azure:*|gs:*) ;;
        *) fail 'El repositorio debe ser remoto (S3 HTTPS, SFTP, REST HTTPS, B2, Azure o GCS)' ;;
    esac
    [ -n "${RESTIC_PASSWORD_FILE:-}" ] && [ -r "$RESTIC_PASSWORD_FILE" ] \
        || fail 'Define un RESTIC_PASSWORD_FILE legible (fuera del repositorio Git)'
    export RESTIC_CACHE_DIR=${RESTIC_CACHE_DIR:-/var/cache/uno-visitas-restic}
    mkdir -p "$RESTIC_CACHE_DIR"
    # Restic cifra contenido y nombres antes de enviarlos. Incluye secretos de recuperación.
    # No se ejecuta init aquí: un destino mal escrito debe fallar, no crear otro repositorio.
    restic backup --host "$backup_host" --tag uno-visitas \
        "$destination" "$runtime_env" "$compose_file"
    restic check
    # paths cambia con cada dump; agrupar por host,tags hace efectiva la retención.
    restic forget --host "$backup_host" --tag uno-visitas --group-by host,tags \
        --keep-last 1 --keep-daily "$daily" --keep-weekly "$weekly" \
        --keep-monthly "$monthly" --prune
    marker=$(mktemp "$backup_dir/.offsite-success-XXXXXX")
    date -u +%Y-%m-%dT%H:%M:%SZ > "$marker"
    mv "$marker" "$backup_dir/last-offsite-success"
    printf 'Respaldo cifrado externo y retención completados.\n'
else
    printf 'Solo respaldo local; UNO_BACKUP_OFFSITE=0 (sin protección fuera del VPS).\n'
fi

# Solo después del éxito completo; los .partial y los dumps de un envío fallido se conservan.
find "$backup_dir" -maxdepth 1 -type f -name 'uno-*.dump' -mtime "+$local_days" -delete
