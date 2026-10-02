# Respaldos de UNO Visitas

El script `infra/backup.sh` prepara un dump PostgreSQL en `.partial`, comprueba su índice y
recorre todo el archivo con `pg_restore --file=/dev/null`. Solo entonces lo renombra a `.dump`
en el mismo directorio. Esta comprobación detecta daños de archivo, pero no sustituye un
ensayo de restauración con PostgreSQL.

Con `UNO_BACKUP_OFFSITE=1`, restic cifra el dump, `runtime.env` y el compose de producción
antes de enviarlos a un repositorio remoto. Aplica `restic check`, retiene 7 copias diarias,
4 semanales, 6 mensuales y al menos la última, agrupadas por host y etiqueta. La retención
local (14 días) se ejecuta después de que esas operaciones terminen correctamente. Un error
de dump conserva el `.partial`; un error remoto conserva el dump válido y los anteriores.

La configuración entregada tiene `UNO_BACKUP_OFFSITE=0`: el respaldo externo **no está
activado**. Falta elegir un destino del usuario, sus credenciales y custodiar la contraseña
de cifrado fuera del VPS. No colocar valores reales en Git, mensajes de chat ni comandos
con secretos como argumentos.

## Instalar en el servidor, después de revisar el cambio

Estos pasos se ejecutan como root en Ubuntu/Debian. Solo instalan la unidad propia de UNO;
no reinician Docker, PostgreSQL, nginx ni otras aplicaciones del servidor.

```sh
apt-get update
apt-get install --no-install-recommends restic util-linux
install -d -m 700 /etc/uno-visitas /usr/local/libexec/uno-visitas
install -d -m 700 /opt/uno-visitas/backups /var/cache/uno-visitas-restic
install -m 700 /opt/uno-visitas/current/infra/backup.sh /usr/local/libexec/uno-visitas/backup.sh
# Primera instalación únicamente: conservar la configuración existente en actualizaciones.
test -e /etc/uno-visitas/backup.env || install -m 600 \
  /opt/uno-visitas/current/infra/backup.env.example /etc/uno-visitas/backup.env
install -m 644 /opt/uno-visitas/current/infra/systemd/uno-visitas-backup.service /etc/systemd/system/
install -m 644 /opt/uno-visitas/current/infra/systemd/uno-visitas-backup.timer /etc/systemd/system/
chown root:root /etc/uno-visitas/backup.env /opt/uno-visitas/runtime.env
chmod 600 /etc/uno-visitas/backup.env /opt/uno-visitas/runtime.env
systemctl daemon-reload
```

El script instalado pertenece a root y no se ejecuta desde el checkout de un desarrollador.
En cada actualización, volver a instalar explícitamente el script y la unidad revisados.
Si cambian las rutas de datos/caché, actualizar también `ReadWritePaths` de la unidad.
El proyecto de Compose debe seguir llamándose `uno-visitas`; el script solo hace `exec`
contra su PostgreSQL ya existente. No necesita crear, arrancar ni recrear contenedores.

## Elegir y preparar el destino externo

Usar un repositorio exclusivo de UNO **fuera de este VPS**, con un prefijo/bucket dedicado.
Para S3 compatible, el usuario del respaldo necesita lectura, escritura, listado y borrado
solo de ese prefijo (restic usa borrado para locks y retención). Guardar en
`/etc/uno-visitas/backup.env`, mediante editor local:

```sh
RESTIC_REPOSITORY='s3:https://HOST/BUCKET/PREFIX'
AWS_ACCESS_KEY_ID='VALOR_DEL_PROVEEDOR'
AWS_SECRET_ACCESS_KEY='VALOR_DEL_PROVEEDOR'
AWS_DEFAULT_REGION='REGION_DEL_PROVEEDOR'
RESTIC_PASSWORD_FILE=/etc/uno-visitas/restic-password
```

Los valores anteriores son marcadores, no un destino existente. SFTP en otro servidor,
REST por HTTPS, B2, Azure o GCS también sirven; usar las variables de credenciales de su
backend según la [documentación oficial de restic](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html).
Para SFTP, usar llave dedicada, comprobar la huella del servidor por un canal independiente
y registrar `known_hosts` antes de automatizar. La unidad admite lectura de `~/.ssh`, pero
no escritura: la primera conexión debe prepararse manualmente. Nunca desactivar la
verificación del host SSH para hacer pasar un respaldo.

Crear una contraseña aleatoria para el repositorio y guardarla en el gestor de contraseñas
del equipo, junto a la URL del destino y las credenciales de recuperación. Si ya existe el
archivo, **no sobrescribirlo**:

```sh
umask 077
if [ ! -e /etc/uno-visitas/restic-password ]; then
  (set -C; openssl rand -base64 48 > /etc/uno-visitas/restic-password)
else
  printf 'Se conserva la contraseña existente.\n'
fi
chmod 600 /etc/uno-visitas/restic-password
```

Abrir una shell de administración, cargar la configuración y crear el repositorio **una
sola vez**, después de confirmar su ubicación. Para uno ya existente, usar `restic snapshots`
en lugar de `restic init`:

```sh
set -a
. /etc/uno-visitas/backup.env
set +a
restic init
restic snapshots
```

Cambiar `UNO_BACKUP_OFFSITE=1` con el editor y ejecutar una primera copia:

```sh
systemctl start uno-visitas-backup.service
systemctl status uno-visitas-backup.service --no-pager
journalctl -u uno-visitas-backup.service -n 40 --no-pager
cat /opt/uno-visitas/backups/last-offsite-success
```

Solo si finaliza sin errores, hacer el ensayo de restauración siguiente y habilitar el timer:

```sh
systemctl enable --now uno-visitas-backup.timer
systemctl list-timers uno-visitas-backup.timer
```

El timer corre a las 07:00 UTC (02:00 en Bogotá) con una variación de hasta 2 minutos.
Configurar el monitor del equipo para alertar si la unidad queda `failed` o si
`last-offsite-success` tiene más de 26 horas. El archivo solo cambia tras copia, verificación
y retención remotas exitosas. Este repositorio no configura un correo ni un proveedor de
alertas. Verificar además espacio libre: un fallo prolongado conserva los dumps para
recuperación y necesita intervención antes de llenar el disco.

## Ensayo de restauración y recuperación

Hacerlo en una máquina aislada de pruebas o de recuperación. Preparar restic, PostgreSQL 16
y Docker si se usa el ejemplo. Recuperar URL/credenciales y contraseña desde su custodia
externa, cargar la configuración y listar las copias:

```sh
restic snapshots --host uno-visitas --tag uno-visitas
restic check --read-data
install -d -m 700 /srv/uno-recovery
restic restore ID_SNAPSHOT_ELEGIDO --target /srv/uno-recovery --verify
find /srv/uno-recovery -type f -name 'uno-*.dump'
```

`--verify` contrasta el contenido restaurado con el snapshot. Las rutas originales están
debajo de `/srv/uno-recovery`; ahí también debe aparecer el `runtime.env`, que conserva JWT,
VAPID y configuración de proveedores. Mantenerlo con permisos 600 y usarlo solo para una
recuperación autorizada. Un ensayo no debe arrancar la aplicación ni su worker con llamadas,
correo o Tavus reales habilitados.

Restaurar en un PostgreSQL nuevo, sin puertos publicados y con un volumen exclusivo de prueba
(`uno-restore-check-data`). Comprobar que esos nombres están libres antes de crearlos:

```sh
(
set -eu
if docker container inspect uno-restore-check >/dev/null 2>&1 || \
   docker volume inspect uno-restore-check-data >/dev/null 2>&1; then
  printf 'Los recursos de prueba ya existen; se cancela para no reutilizarlos.\n' >&2
  exit 1
fi
if [ ! -e /srv/uno-recovery/postgres-test.env ]; then
  (umask 077; set -C; { printf 'POSTGRES_PASSWORD='; openssl rand -hex 32; } \
    > /srv/uno-recovery/postgres-test.env)
fi
test -r /srv/uno-recovery/postgres-test.env
docker volume create --label uno.restore-test=true uno-restore-check-data
docker run -d --name uno-restore-check --label uno.restore-test=true --network none \
  --env-file /srv/uno-recovery/postgres-test.env \
  -v uno-restore-check-data:/var/lib/postgresql/data postgres:16-alpine
ready=0
for attempt in $(seq 1 30); do
  if docker exec uno-restore-check pg_isready -U postgres; then ready=1; break; fi
  sleep 2
done
test "$ready" = 1 || { printf 'PostgreSQL no inició en 60 segundos.\n' >&2; exit 1; }
docker exec uno-restore-check createdb -U postgres uno_restore
docker exec -i uno-restore-check pg_restore -U postgres -d uno_restore \
  --no-owner --no-privileges --exit-on-error < /RUTA/AL/DUMP/RESTAURADO.dump
docker exec uno-restore-check psql -U postgres -d uno_restore -v ON_ERROR_STOP=1 \
  -c 'SELECT version_num FROM alembic_version;' \
  -c 'SELECT count(*) AS usuarios FROM app_user;' \
  -c 'SELECT count(*) AS visitas FROM visit;'
)
```

El ensayo solo se da por bueno si `pg_restore` termina con código 0 y se comprueban datos
esperados (usuarios, visitas, reportes y la fecha elegida). Registrar snapshot, duración y
resultado. Repetir mensualmente y después de cambios de esquema. Al terminar, borrar
exclusivamente el contenedor y volumen de prueba que se acaban de crear:

```sh
(
set -eu
test "$(docker inspect -f '{{index .Config.Labels "uno.restore-test"}}' uno-restore-check)" = true
test "$(docker volume inspect -f '{{index .Labels "uno.restore-test"}}' uno-restore-check-data)" = true
docker rm -f uno-restore-check
docker volume rm uno-restore-check-data
)
```

Para una recuperación real, restaurar en una instancia nueva, comprobar los mismos datos,
recuperar el release indicado en `runtime.env` y aplicar sus migraciones antes de reabrir
tráfico. Mantener el worker detenido hasta revisar qué notificaciones/llamadas estaban
pendientes en el snapshot; así se evita reproducir acciones externas antiguas. No ejecutar
`docker compose down -v` en el servidor compartido ni restaurar encima de `pgdata` sin el
procedimiento de recuperación y la autorización de mantenimiento correspondientes.

## Comprobaciones locales de este cambio

```sh
sh -n infra/backup.sh
python -m unittest discover -s infra/tests -v
```

Los dobles de Docker/restic prueban archivo vacío, error de dump/validación, fallos de copia,
comprobación y retención externa, modo local explícito y rechazo de un repositorio local.
No prueban un proveedor remoto ni una restauración real; esos resultados se registran al
activar el destino elegido. En Windows se usa Git Bash y `flock` se simula.

La retención usa [las reglas de restic](https://restic.readthedocs.io/en/stable/060_forget.html)
con `--group-by host,tags`, porque la ruta del dump cambia diariamente. El cifrado externo no
cifra los dumps locales de preparación: sus directorios y archivos son privados de root;
si se necesita cifrado local en reposo, debe activarse también en el almacenamiento del VPS.
