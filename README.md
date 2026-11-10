# UNO Visitas

## Versión recuperada del VPS (r33, 30 de octubre de 2026)

Este repositorio conserva la versión activa del VPS (`releases/20261030-context-r33`,
capturada el 9 de noviembre; sin cambios desde el 30 de octubre). Los SHA-256 están en
[`deployments/vps-20261030-r33/manifest.json`](deployments/vps-20261030-r33/manifest.json).
Qué cambió desde la captura anterior y los límites de esta copia están en
[la nota de recuperación](docs/operaciones/recuperacion-vps-2026-10-30.md).

**App Territorio (`/territorio/`):** su fuente TypeScript está en [`apps/territory`](apps/territory)
y se instala con npm (`npm ci`), fuera del workspace de pnpm.

**Web antigua (`/`):** el VPS conserva la compilación, pero no sus fuentes TypeScript actuales.
`apps/web/src` conserva la última versión disponible en Git (`9a7bca6`); recompilarla
produce una interfaz distinta de la desplegada. El Dockerfile web usa por defecto
[`deployments/vps-20261030-r33/web`](deployments/vps-20261030-r33/web), la copia exacta de la release activa.
Para usar deliberadamente una compilación nueva, pasa `--build-arg WEB_DIST_DIR=apps/web/dist`.
La captura anterior sigue en [`deployments/vps-20261006`](deployments/vps-20261006).

Las credenciales, la configuración privada, la base de datos y los reportes de producción
se mantienen fuera del repositorio. Las verificaciones históricas de las secciones siguientes
corresponden a sus fechas; no certifican esta captura.

PWA para visitadores médicos: agenda propia, «Llegué / Terminé», llamada de resumen y, con el tiempo, una capa de inteligencia que aprende de cada visita.

Los documentos de diseño están en [`../Plan UNO Visitas`](../Plan%20UNO%20Visitas) (arquitectura 01, plan de trabajo 02, inteligencia y ML 03, práctica con médico virtual 04). Este repositorio es la construcción de ese plan.

Correcciones del 2 de octubre: [alcance, pruebas y aplicación operativa](docs/operaciones/validacion-2026-10-02.md).
Los [respaldos externos](docs/operaciones/respaldos.md) quedan preparados y requieren configurar su destino antes de activarlos.

## Estado (30 de septiembre de 2026)

| Módulo | Qué hace | Estado |
| --- | --- | --- |
| **Auth** | Ingreso con celular + PIN (argon2id), JWT de 24 h, refresco rotatorio en cookie `httpOnly`, bloqueo por fuerza bruta | ✅ Hecho y probado |
| **Catálogo** | Líneas de producto (RESPI, OSTRU, GASTRU), instituciones, médicos y panel del visitador. Alta rápida de médico desde el teléfono | ✅ Hecho y probado |
| **Agenda** | Ver Hoy y la semana, agendar (≤ 3 toques), cambiar hora, «No se realizó». Funciona sin red | ✅ Hecho y probado |
| **Sync** | Cola local (IndexedDB) → `POST /v1/sync` idempotente → bajada incremental `GET /v1/me/state`. Reintentos 1-2-4-8 min | ✅ Hecho y probado |
| **Avisos** | Notificaciones en el teléfono (Web Push) y por correo (pre-registrado por el administrador o verificado con código): recordatorio antes de cada visita y resumen del día | ✅ Hecho y probado |
| **Bitácora de eventos** | `domain_event` append-only con doble marca de tiempo (base de la capa de inteligencia) | ✅ Hecho y probado |
| **Llegué / Terminé + ubicación** | Permiso de ubicación obligatorio, una lectura por toque (sin GPS continuo), geocerca calculada en el teléfono y en el servidor, reintento de ubicación | ✅ Hecho y probado ([ADR-22](docs/adr/ADR-22-ubicacion-obligatoria-un-toque.md)). Pendiente dentro de E4: deshacer, motivo de «lejos», cierre tardío, «Otro médico aquí», referencia automática y señales de consistencia |
| **Llamada de resumen** | Una llamada por visita por defecto; conversación adaptativa, información nueva, nota libre, lectura del resumen y confirmación verbal. Recoge lo pendiente sin convertir la visita en una encuesta de pedidos. Reintentos y espera mientras el visitador está en otra visita | ✅ Código y agente actualizado en ElevenLabs. Telefonía con Twilio ([ADR-23](docs/adr/ADR-23-llamadas-elevenlabs-telyaco-cola-propia.md)). Meta de 1–2 min por visita; pendiente medir duración y naturalidad del nuevo guion con voz real |
| **Historial y ficha** | Producto, objetivo, conversación, intereses/desintereses, reacción/receptividad, preguntas, información nueva, competencia, compromisos, próxima acción/fecha y nota libre; institución, ubicación y llegada/salida. Confirmación verbal respaldada por la transcripción, revisión y correcciones en la app | ✅ Recorrido simulado completo. Los campos no informados quedan pendientes; correcciones y confirmación manual funcionan sin red |
| **Entrenar** | Pestaña «Entrenar»: cuatro escenarios de ESOMED con un médico virtual en video (Tavus) y voz de ElevenLabs. En cada uno: lectura, formulario de 4 preguntas con explicación y fuente, visita de hasta 5 minutos y resultado con la rúbrica de Novamed (6 competencias × 5), sin puntos, trofeos ni bloqueos. El avance queda guardado por visitador; la gerencia tiene su resumen en la API (`/v1/manager/training`) | ✅ Implementado (servidor: 54 pruebas; app: 232 pruebas en total). **30 sep:** 4 médicos publicados en la nueva cuenta y creación comprobada en `test_mode` (sin costo). El usuario confirmó la entrada y reproducción del médico en Chrome para Android tras corregir la carga; pendiente validar la nitidez del nuevo encuadre vertical y una visita completa con evaluación ([ADR-24](docs/adr/ADR-24-entrenar-medico-virtual-tavus.md)) |
| Vista gerencial | Actividad de 30 días, médicos, duración, productos, cumplimiento por visitador, alertas e insights con evidencia | ✅ Conectada a reportes de UNO con acceso por rol. Exportación CSV pendiente |
| Inteligencia y decisión | Historial médico × línea realmente presentada y próximos pasos basados en compromisos confirmados; programación en la agenda desde la cuenta del visitador | ✅ Reglas del piloto conectadas a datos de UNO y demo completa. ⏳ Conexión con ESOMED y validación con usuarios; ML no entrenado |

## Explorar el módulo de Inteligencia

Con la web en desarrollo, abre `http://localhost:5173/inteligencia/demo`. El módulo usa un marco
de celular (hasta 480 px) también en escritorio. La navegación del visitador tiene cuatro accesos:
**Hoy, Agenda, Recomendaciones y Entrenar**. Historial se conserva dentro de la cuenta.

Recomendaciones muestra una sola próxima visita destacada y una lista breve. **Ver detalles** abre
el propósito de la visita y módulos de evidencia, historial, productos, frecuencia y territorio;
solo un módulo puede permanecer abierto a la vez. **Programar visita** permite aceptar el horario
sugerido o cambiarlo y después abrir directamente el día programado.

Los perfiles, el calendario de ejemplo, el aprendizaje y el resumen del equipo están bajo **Más
opciones del módulo**. Allí se encuentran también los selectores de visitador y **Sin datos**,
sin ocupar la pantalla principal. El calendario real del visitador sigue en **Agenda**.

La demostración es pública porque solo contiene datos ficticios; guarda sus cambios en `sessionStorage`
y no escribe en la agenda real ni llama a la API. **Restablecer ejemplo** recupera el escenario inicial.
El recorrido completo está en `http://localhost:5173/inteligencia/demo/visita`: llegada, salida,
llamada con guion simulado (audio opcional del navegador), corrección y confirmación. La visita
confirmada alimenta el dashboard, historial e insights del ejemplo. No usa micrófono ni hace llamadas.

La ruta autenticada `/inteligencia` consulta `/v1/intelligence/snapshot`: hasta 365 días de historial,
panel y agenda. El visitador solo recibe sus datos; gerencia y administración consultan el equipo.
Administradores y gerentes llegan allí al ingresar; los visitadores acceden desde su navegación.
Las recomendaciones de seguimiento requieren un reporte completo y confirmado, una acción pendiente
y una línea identificada en el catálogo a partir del producto reportado. La agenda no demuestra qué
producto se presentó. Si el producto no tiene correspondencia, la línea queda por verificar.
Programar una sugerencia envía un evento real de agenda; descartar o revisar una observación se
conserva en esta sesión. La disponibilidad del médico debe acordarse con el consultorio.

Las alertas son señales de revisión: menos de 3 min, más de 3 horas o duración negativa,
ubicación pendiente, información esencial incompleta, tres visitas de la misma línea en siete días
y contexto sin actualizar durante 90 días. Los insights cuentan menciones confirmadas y excluyen
campos de baja confianza. No implican causalidad ni una evaluación del visitador.
La integración con médicos, visitadores, rutas, instituciones e históricos de ESOMED sigue pendiente.

La verificación de este cambio incluyó el recorrido en navegador hasta programar la fecha corregida,
pruebas de la app y del servidor, y simulaciones de texto del agente: confirmación, correcciones,
visita no realizada, reintento, ausencia de receptividad, datos de paciente y varias visitas.
El agente usa Gemini 3.5 Flash; la llamada del piloto contiene una visita por defecto. Las simulaciones
no comprueban la duración, la transcripción de voz ni la naturalidad: eso queda para la prueba telefónica.

## Estructura

```
apps/web/             PWA (React 19 + TypeScript + Vite + Tailwind 4 + Dexie)
  src/features/       auth · agenda · geo · visit · notifications · training · intelligence
  src/sync/           cola local, motor de sincronización, vista optimista
  src/sw.ts           service worker: precache, navegación offline, avisos push
services/api/         API (FastAPI + SQLAlchemy 2 async + Alembic)
  src/uno/modules/    auth · catalog · agenda · sync · notifications · calls · training
  migrations/         esquema versionado (Alembic)
infra/                docker-compose (PostgreSQL 16 + Mailpit), Dockerfile de la API
  elevenlabs/         el agente de voz como código: guion, voz, turnos y banco de escenarios
docs/contratos/       contrato de eventos de sincronización y de la API
docs/adr/             decisiones de arquitectura
```

## Requisitos

Node 22+ (con `corepack`), Python 3.12 gestionado por [`uv`](https://docs.astral.sh/uv/) y, opcionalmente, Docker.

> **OneDrive:** esta carpeta está dentro de OneDrive y `node_modules/` y `.venv/` tienen miles de archivos. Si la sincronización molesta, pausa OneDrive mientras instalas o mueve el repositorio fuera de la carpeta sincronizada.
>
> **Windows:** si el sistema bloquea los ejecutables generados (`uno.exe`, `alembic.exe`), usa siempre `python -m`: `uv run python -m uno.cli …`.

## Puesta en marcha (desarrollo, sin Docker)

```powershell
# 1. Backend
cd services/api
uv sync
copy .env.example .env                       # y completa UNO_JWT_SECRET
uv run python -m uno.cli vapid-generate      # pega las dos llaves VAPID en .env
uv run python -m uno.cli db-upgrade          # crea la base (SQLite en desarrollo)
uv run python -m uno.cli seed-demo           # usuarios y agenda ficticios (PIN en src/uno/seed.py)
uv run python -m uvicorn uno.main:app_factory --factory --port 8000

# 2. App (otra terminal)
cd apps/web
corepack pnpm install
corepack pnpm dev                            # http://localhost:5173 (proxy a la API)
```

En desarrollo, `UNO_EMBEDDED_WORKER=true` corre el trabajador de recordatorios dentro de la API y `UNO_EMAIL_BACKEND=file` deja cada correo como `.eml` en `services/api/var/mail/`.

Para enviar correos reales a cualquier destinatario del piloto, configura una sola cuenta
remitente con SMTP (`UNO_EMAIL_BACKEND=smtp`, host, puerto, TLS, usuario y `UNO_EMAIL_FROM`).
Guarda `UNO_SMTP_PASSWORD` solo en `~/.uno-visitas/secrets.env`, fuera del repositorio.
Con Gmail personal, usa una contraseña de aplicación de una cuenta con verificación en dos pasos;
la contraseña normal de Google no sirve para este flujo. Cada visitador confirma su propio correo
desde **Mi cuenta → Avisos**. Mientras el backend sea `file`, la app indica que el envío no está
conectado y el botón de prueba no afirma haber entregado un correo.

### Con PostgreSQL 16 (Docker)

```powershell
cd infra
"UNO_JWT_SECRET=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" | Out-File .env -Encoding ascii
docker compose up --build            # API en :8000, correos en http://localhost:8025
```

## Usuarios

En el piloto, la pantalla **Crear cuenta** pide nombre, celular, correo, PIN y un código de
invitación. Configura `UNO_PILOT_INVITE_CODE` fuera del repositorio para habilitarla; sin código,
el registro público queda cerrado. Las cuentas nuevas son visitadores. El correo queda guardado,
pero no recibe avisos hasta que el usuario lo confirme en **Más → Avisos**. En desarrollo,
`UNO_EMAIL_BACKEND=file` escribe esos códigos en `services/api/var/mail/`; para recibirlos en el
celular hace falta configurar SMTP.

```powershell
uv run python -m uno.cli create-user --name "Ana Pérez" --phone +573001234567 --role rep --email ana@correo.com
uv run python -m uno.cli set-pin --phone +573001234567
uv run python -m uno.cli set-email --phone +573001234567 --email ana@correo.com   # queda verificado
```

## Llegué / Terminé y ubicación

- **Permiso obligatorio.** Sin permiso de ubicación no se entra a la app (`features/geo/LocationGate.tsx`). Una lectura que falla no bloquea: el toque se registra igual como «sin GPS» y se puede reintentar durante 2 minutos.
- **Un toque, una lectura.** Al tocar se pide la posición una vez (alta precisión, tope de 8 s); no hay seguimiento. El toque queda guardado al instante y la ubicación se adjunta cuando llega. Solo `features/geo/capturar.ts` toca la API del navegador (lo verifica una prueba).
- **Geocerca.** El estado (`verificada`, `lejos`, `imprecisa`, `sin_referencia`, `sin_gps`) sale de la misma regla en el teléfono y en el servidor; ambos pasan los 20 casos de [`docs/contratos/geocerca-casos.json`](docs/contratos/geocerca-casos.json). Las coordenadas se guardan solo en la tabla `visit`, nunca en la bitácora.
- **Referencia del lugar.** Cada institución tiene su punto y radio (300 m por defecto). Se fija con:

```powershell
cd services/api
uv run python -m uno.cli db-upgrade    # una vez, aplica la migración 0002
uv run python -m uno.cli set-institution-ref --name "Hospital San Rafael" --lat 4.6533 --lng -74.0836 --radius 300
```

  Las instituciones que ya existían en una base anterior conservan 150 m; súbelas con `--radius 300`. Sin referencia, la ubicación se guarda y el estado es `sin_referencia`.
- **Probar en un teléfono.** *Más → Probar ubicación* muestra una lectura suelta contra un punto (pega las coordenadas desde Google Maps). Necesita HTTPS: usa el túnel de la sección de notificaciones.

## Llamada de resumen (ElevenLabs + Twilio)

Antes de cada reunión, el servidor programa una llamada de recordatorio: 5 minutos antes por
defecto (15:00 → 14:55), configurable o desactivable en **Mi cuenta → Avisos**. Esta llamada
pregunta «Oye, ¿ya estás cerca?» y no solicita un reporte. Es independiente de push y correo.

Si pasan 30 minutos desde «Llegué» sin «Terminé», llama para preguntar si ya terminó. Si el
visitador sigue reunido, conserva la reunión abierta y espera a «Terminé». Solo un cierre
explícito por voz registra una salida; queda sin GPS, nunca se inventa una ubicación.

Al tocar «Terminé», el servidor programa una llamada para esa visita por defecto. Primero ofrece
«Oye, ¿tienes tiempo para hacer tu resumen o prefieres hacerlo por escrito en la app?».
Si elige escribir o no tiene tiempo, queda el indicador de resumen pendiente y puede escribir
desde el historial sin una entrevista previa. Si acepta hablar, el agente escucha
el relato, pregunta solo por datos pendientes, ofrece una nota libre, lee el resumen y espera la
confirmación explícita. Una corrección exige nueva lectura y confirmación. La ficha se guarda
confirmada solo si el análisis y la transcripción respaldan esa aceptación; en otro caso queda
para revisar en la app. La información puede estar confirmada y seguir incompleta.

Solo llama entre las 7:00 y las 19:00, espera si el visitador está en otra visita incluso en un
reintento y reintenta a los +5 y +15 min dentro del plazo original. El resumen debe completarse
y confirmarse en 30 minutos desde el primer aviso telefónico; el servidor registra ese aviso
cuando el proveedor acepta la marcación. Un fallo al marcar no inicia el plazo y los reintentos
no lo reinician. Si confirma que sigue reunido, se quita el plazo provisional. Al vencer, solo
el resumen queda inválido: se conserva la visita y puede guardarse un texto tardío, marcado
fuera de plazo. No se hace una llamada de cierre por un resumen ya vencido. Una confirmación
hecha sin red antes del límite conserva su validez al sincronizar.
`UNO_CALL_MAX_VISITS_PER_CALL=1` es el valor predeterminado; se pueden agrupar hasta 5 con confirmación
individual. La meta de 1–2 minutos es por visita, no por lote. No es un corte que fuerce datos inventados.

**Las llaves viven fuera del repositorio y de OneDrive**, en `~/.uno-visitas/secrets.env` (la lee `config.py`):

```
UNO_ELEVENLABS_API_KEY=…
UNO_ELEVENLABS_AGENT_ID=…            # lo imprime elevenlabs-apply
UNO_ELEVENLABS_PHONE_NUMBER_ID=…     # lo imprime elevenlabs-assign-number
UNO_CALL_BACKEND=elevenlabs          # off (por defecto: nunca llama) | fake | elevenlabs
UNO_CALL_ALLOWED_PHONES=+573001234567   # fuera de producción, solo se llama a estos
# UNO_ELEVENLABS_PHONE_CHANNEL=auto     # auto (se detecta) | twilio | sip_trunk
```

```powershell
cd services/api
uv run python -m uno.cli elevenlabs-apply                 # crea o actualiza el agente desde infra/elevenlabs
uv run python -m uno.cli elevenlabs-numbers               # números de la cuenta y qué agente usa cada uno
uv run python -m uno.cli elevenlabs-assign-number --phone-number-id phnum_…
uv run python -m uno.cli elevenlabs-golden --show         # banco de escenarios (texto; no llama a nadie)
uv run python -m uno.cli call-test --phone +573001234567  # prueba REAL: hace sonar ese celular
uv run python -m uno.cli calls-list                       # últimas llamadas
uv run python -m uno.cli calls-show 01a0eb7f              # fichas y transcripción de una llamada
```

- **La cuenta de ElevenLabs es compartida con otras campañas.** Los comandos solo tocan el agente «UNO Visitas · Entrevista de visita»; `elevenlabs-assign-number` **se niega** a quitarle un número a otro agente salvo `--force-reassign`.
- **Cambiar lo que pregunta el agente** es editar `infra/elevenlabs/prompt.es.md` y correr `elevenlabs-apply`; después `elevenlabs-golden --names` comprueba conversación, extracción y confirmación (10 escenarios, incluidos corrección y nueva lectura, receptividad no inferida y resumen sin confirmar).
- **Qué se extrae** está en `modules/calls/schema.py`: 21 campos simples del proveedor, con un objeto JSON de detalles y un indicador de confirmación. Las visitas adicionales viajan como JSON. Un detalle dañado no elimina los demás datos. Producto, objetivo, conversación, resultado, compromisos, próximo paso y receptividad son esenciales; el resto permanece visible como no informado si falta. «No quedaron compromisos» es distinto de no haberlo preguntado.
- **Resultado**: por webhook firmado (`POST /v1/webhooks/elevenlabs`, opcional) o por consulta directa cada 5 s (siempre activa). Ambos son idempotentes.
- **Probar con tu celular**: `UNO_CALL_PHONE_OVERRIDE=+57…` desvía TODAS las llamadas a ese número (solo desarrollo; el servidor se niega a arrancar en producción con esta variable). Así la cuenta de demostración hace sonar el teléfono de quien prueba. Sin reintentos: `UNO_CALL_RETRY_MINUTES=` (vacío).
- **Nombres y datos**: `UNO_CALL_INCLUDE_DOCTOR_NAMES=true` permite el saludo contextual por defecto; se puede desactivar. El agente excluye identificadores de pacientes de la ficha. Coordenadas y transcripción no se envían al dashboard. ElevenLabs conserva las conversaciones 30 días (`infra/elevenlabs/agent.json`).

## Entrenar (médico virtual: Tavus + voz de ElevenLabs)

El visitador escoge un escenario, repasa la lectura, hace el formulario y conversa por voz con el médico virtual (video en el celular, cámara propia apagada). Al terminar, el servidor trae la transcripción, la evalúa con la rúbrica de Novamed y muestra qué mejorar, el momento clave y la mejor respuesta aprobada. Diseño completo en el documento 04 y en [ADR-24](docs/adr/ADR-24-entrenar-medico-virtual-tavus.md).

```
UNO_TRAINING_BACKEND=tavus           # off (por defecto: sin médico) | fake (simulado, sin video) | tavus (real)
UNO_TAVUS_API_KEY=…                  # solo en ~/.uno-visitas/secrets.env
UNO_TAVUS_CALLBACK_BASE_URL=https://… # opcional: URL pública de la API; sin ella la transcripción se consulta cada 5 s
```

```powershell
cd services/api
uv run python -m uno.cli db-upgrade                  # migración 0004: tablas de Entrenar
uv run python -m uno.cli training-apply --dry-run    # qué publicaría en Tavus (cara, voz, tamaño del prompt)
uv run python -m uno.cli training-apply              # publica los médicos cuyo contenido cambió
uv run python -m uno.cli training-check              # ¿Tavus acepta conversaciones? (prueba sin costo)
uv run python -m uno.cli training-attempts           # últimas prácticas, puntaje y visitador
uv run python -m uno.cli training-cleanup            # borra en Tavus los médicos de versiones retiradas
```

- **Contenido como código.** Los médicos, lecciones, formularios y el banco de mensajes aprobados están en `services/api/src/uno/modules/training/content/`. Cambiar cara, voz, nombre o comportamiento es editar el JSON del escenario y correr `training-apply`: crea una versión nueva y las prácticas siguientes la usan.
- **La cuenta de Tavus es compartida con otros proyectos.** Los comandos solo crean o borran médicos cuyo nombre empieza por «UNO Entrenar». El nombre lleva la huella del contenido: publicar lo mismo desde otra base de datos reutiliza el médico existente, no lo duplica.
- **Cambiar de cuenta de Tavus:** después de actualizar la clave en `~/.uno-visitas/secrets.env`, corre `training-apply` y reinicia la API. El publicador comprueba que los médicos de la base local existen en la cuenta actual; si no, publica versiones nuevas y conserva las anteriores para el historial.
- **Sin créditos no se rompe nada.** Al abrir Entrenar, el servidor pregunta a Tavus en modo de prueba (sin costo, como mucho cada 5 minutos). Si no hay créditos, la app muestra «no disponible por ahora», no pide el micrófono y deja hacer la lectura y el formulario. Cuando se recarguen, basta con volver a abrir la pestaña (el aviso se va en 5 minutos como máximo).
- **Calificación preliminar.** Hoy la evaluación sale de reglas (las mismas del prototipo de Sangil) y la app lo dice. El juez con IA (documento 04, D3) la afinará cuando haya llave. Los umbrales de aprobación por escenario son una propuesta hasta que Novamed decida (D9).
- **Probar sin Tavus:** `UNO_TRAINING_BACKEND=fake` simula al médico con una visita de ejemplo y deja ver el resultado completo. Las prácticas por día (`UNO_TRAINING_ATTEMPTS_PER_DAY`, 6) y los minutos por visita (`UNO_TRAINING_MAX_CALL_SECONDS`, 300) tienen tope.
- **Privacidad:** consentimiento versionado antes de la primera visita; la transcripción se guarda en `practice_turn` y nunca en la bitácora de eventos.

## Pruebas

```powershell
cd services/api
uv run python -m pytest                           # SQLite (rápido)
$env:UNO_TEST_DB = "postgres"; uv run python -m pytest   # PostgreSQL 16 real (paquete pgserver, sin Docker)
uv run python -m ruff check src tests migrations

cd ../../apps/web
corepack pnpm test && corepack pnpm typecheck && corepack pnpm build
```

## Notificaciones: cómo se prueban

- **Correo:** en desarrollo se escriben en `services/api/var/mail/`. Con Docker, en Mailpit (`http://localhost:8025`).
- **Web Push:** exige HTTPS o `localhost`, permiso del usuario y una llave VAPID. En iPhone solo funciona con la app **instalada** en la pantalla de inicio (iOS ≥ 16.4). Para probar en un celular real hace falta un túnel HTTPS (por ejemplo `cloudflared`). Con `UNO_PUSH_BACKEND=webpush` el servidor envía de verdad; con `log` solo deja constancia.
- El envío cifrado y la firma VAPID están verificados con un servicio de push falso local (`tests/test_webpush_sender.py`).

## Reglas del proyecto

Las heredadas de los documentos 01–03: el teléfono nunca espera a la red; todo cambio del visitador es un evento idempotente (UUIDv7) por `/v1/sync`; nunca se pierde una visita por falta de ubicación (lo obligatorio es el *permiso*, ADR-22); GPS solo en los dos toques, una lectura por toque; sin datos de pacientes; ningún secreto en el repositorio.
