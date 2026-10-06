# Recuperación de la versión activa del VPS

Captura: 6 de octubre de 2026. El instante UTC exacto y los hashes están en
[`manifest.json`](../../deployments/vps-20261006/manifest.json).

## Qué contiene

- API y trabajador: imagen `uno-visitas-api:20261002T162421Z-finish-only`.
  Se recuperaron los 90 archivos del paquete `uno` que Python importa desde
  `site-packages`, las migraciones y los archivos de instalación del contenedor.
  El paquete instalado de la API coincide con el del trabajador.
- Web: imagen `uno-visitas-web:20261002T161400Z`. Los 65 archivos servidos se
  conservan en `deployments/vps-20261006/web`, incluida la PWA, las fotografías
  y sus recursos. El Dockerfile web usa esta carpeta por defecto.
- Infraestructura y guiones: archivos de la release activa
  `/opt/uno-visitas/releases/20261002T134402Z`, y la configuración nginx del
  contenedor web. La configuración privada y las credenciales no se exportan.
- Historial: se conserva la rama `integracion/pendientes-y-entrenar-v2` como
  antecesora de esta recuperación; no se reescribe el historial del repositorio.

## Diferencias que importan

La carpeta de release y `/app/src` no incluyen la última corrección de
`modules/calls/service.py`. La imagen activa la aplica en el paquete instalado:
solo se planifica el resumen tras terminar y se limita a una marcación por visita.
Esta recuperación toma el archivo instalado, no la copia anterior de la release.

El VPS y sus archivos de despliegue solo conservan el frontend compilado.
Las fuentes disponibles en Git pertenecen a `9a7bca6` y no reproducen la web activa;
una compilación de las fuentes locales también produjo recursos diferentes.
Por eso la compilación recuperada se conserva aparte y no se sustituye al ejecutar
`web:build`. Recuperar las fuentes actuales del frontend sigue siendo una tarea
independiente. No se reconstruyó código TypeScript a partir del JavaScript minificado.

El Dockerfile original del VPS está en
[`web.Dockerfile.deployed`](../../deployments/vps-20261006/web.Dockerfile.deployed).
El único ajuste de empaquetado del Dockerfile del repositorio es `WEB_DIST_DIR`,
que selecciona la compilación recuperada. Para una compilación nueva se puede usar
`--build-arg WEB_DIST_DIR=apps/web/dist` después de construirla conscientemente.

## Verificación de la captura

Se compararon los SHA-256 del archivo descargado, de cada archivo de código Python
recuperado y de cada archivo de la web. La identidad de los contenedores, sus imágenes,
la release activa y los archivos de la release permanecieron iguales durante la copia.
El endpoint de salud devolvió `estado=verde` y `base_de_datos=true`.

También se comprobó la sintaxis de 96 archivos Python y la existencia de 176 referencias
estáticas del frontend. Dentro de los contenedores de API y trabajador se verificaron
la política de una sola marcación y la desactivación del planificador de llamadas previas
y chequeos, sin realizar llamadas. No se ejecutó la suite completa de las fuentes antiguas.
La importación local en Windows encontró un bloqueo de Control de aplicaciones sobre
una DLL de SQLAlchemy; la comprobación de importación y política se realizó en los
contenedores activos, donde pasó.

No se reiniciaron servicios ni se modificaron la aplicación, la base de datos, los
proveedores de llamadas o la configuración del VPS. Esta operación guarda la versión
que ya estaba funcionando; no valida recorridos de usuarios ni realiza un despliegue.

## Restauración y mantenimiento

La API se construye desde `services/api/src`, con las dependencias de
`infra/api-requirements.txt`. La imagen web se construye con los recursos recuperados
usando `infra/web.Dockerfile`. Las imágenes tienen versiones distintas, tal como en
el servidor; la procedencia exacta está en el manifiesto.

Las variables privadas deben suministrarse fuera de Git al usar Compose, según
`infra/docker-compose.prod.yml`. El respaldo de PostgreSQL y la configuración privada
requieren un mecanismo de respaldo separado: no forman parte de esta captura de código.
