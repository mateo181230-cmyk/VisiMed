# UNO Visitas

PWA para visitadores médicos: agenda propia, «Llegué / Terminé», llamada de resumen y, con el tiempo, una capa de inteligencia que aprende de cada visita.

Los documentos de diseño están en [`../Plan UNO Visitas`](../Plan%20UNO%20Visitas) (arquitectura 01, plan de trabajo 02, inteligencia y ML 03, práctica con médico virtual 04). Este repositorio es la construcción de ese plan.

## Estado (29 de septiembre de 2026)

| Módulo | Qué hace | Estado |
| --- | --- | --- |
| **Auth** | Ingreso con celular + PIN (argon2id), JWT de 24 h, refresco rotatorio en cookie `httpOnly`, bloqueo por fuerza bruta | ✅ Hecho y probado |
| **Catálogo** | Líneas de producto (RESPI, OSTRU, GASTRU), instituciones, médicos y panel del visitador. Alta rápida de médico desde el teléfono | ✅ Hecho y probado |
| **Agenda** | Ver Hoy y la semana, agendar (≤ 3 toques), cambiar hora, «No se realizó». Funciona sin red | ✅ Hecho y probado |
| **Sync** | Cola local (IndexedDB) → `POST /v1/sync` idempotente → bajada incremental `GET /v1/me/state`. Reintentos 1-2-4-8 min | ✅ Hecho y probado |
| **Avisos** | Notificaciones en el teléfono (Web Push) y por correo (pre-registrado por el administrador o verificado con código): recordatorio antes de cada visita y resumen del día | ✅ Hecho y probado |
| **Bitácora de eventos** | `domain_event` append-only con doble marca de tiempo (base de la capa de inteligencia) | ✅ Hecho y probado |
| **Llegué / Terminé + ubicación** | Permiso de ubicación obligatorio, una lectura por toque (sin GPS continuo), geocerca calculada en el teléfono y en el servidor, reintento de ubicación | ✅ Hecho y probado ([ADR-22](docs/adr/ADR-22-ubicacion-obligatoria-un-toque.md)). Pendiente dentro de E4: deshacer, motivo de «lejos», cierre tardío, «Otro médico aquí», referencia automática y señales de consistencia |
| **Llamada de resumen** | Al terminar, un agente de voz (ElevenLabs sobre un número de Telyaco) llama al visitador y le hace, como máximo, **seis preguntas** (interés 1–5, resultado —¿te compró o te encargó algo?—, objeción o por qué no —¿la competencia está mejor o no necesitaba cambiar?—, competencia, próximo paso y territorio) y arma una ficha por visita. Reintentos a +5 y +15 min, llamada de cierre a las 18:00, una sola llamada para varias visitas | ✅ Servidor y agente hechos y probados (simulador y 7 escenarios de conversación, 20 de 21 corridas correctas). ✅ **Primera llamada real hecha el 29 de septiembre de 2026** por **Twilio** (+1 570 776 9534 → celular colombiano): 113 s, 5 preguntas hechas y ficha correcta. Telyaco quedó descartado: su troncal rechazó la primera llamada (`403 Auth Failed`) ([ADR-23](docs/adr/ADR-23-llamadas-elevenlabs-telyaco-cola-propia.md)) |
| **Historial y ficha** | Pestaña «Historial»: las visitas por día (Hoy, Ayer…), cada una con su resumen; se confirma con un toque y cada dato se puede corregir. Funciona sin red (los cambios van a la cola) y avisa cuántos resúmenes esperan | ✅ Hecho y probado (servidor: 15 pruebas; app: 19 pruebas; recorrido completo en el navegador con el proveedor simulado) |
| **Entrenar** | Pestaña «Entrenar»: cuatro escenarios de ESOMED con un médico virtual en video (Tavus) y voz de ElevenLabs. En cada uno: lectura, formulario de 4 preguntas con explicación y fuente, visita de hasta 5 minutos y resultado con la rúbrica de Novamed (6 competencias × 5), sin puntos, trofeos ni bloqueos. El avance queda guardado por visitador; la gerencia tiene su resumen en la API (`/v1/manager/training`) | ✅ Hecho y probado (servidor: 53 pruebas; app: 6; recorrido completo con el médico simulado). Los 4 médicos están publicados en Tavus, pero ⛔ **la cuenta de Tavus no tiene créditos**: la app dice «no disponible por ahora» y deja hacer la preparación. Al recargar, funciona sin tocar código ([ADR-24](docs/adr/ADR-24-entrenar-medico-virtual-tavus.md)) |
| Vista gerencial | Lista, evidencia, CSV | ⏳ E7 |
| Inteligencia y decisión | Perfiles médico × línea, recomendación, agenda óptima | ⏳ E11 (después del piloto) |

## Estructura

```
apps/web/             PWA (React 19 + TypeScript + Vite + Tailwind 4 + Dexie)
  src/features/       auth · agenda · geo · visit · notifications · training   (un módulo por carpeta)
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

### Con PostgreSQL 16 (Docker)

```powershell
cd infra
"UNO_JWT_SECRET=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" | Out-File .env -Encoding ascii
docker compose up --build            # API en :8000, correos en http://localhost:8025
```

## Usuarios

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

## Llamada de resumen (ElevenLabs + Telyaco)

Al tocar «Terminé», el servidor agrupa las visitas terminadas del visitador (hasta 5) en **una** llamada, la marca desde un número de Telyaco con un agente de ElevenLabs y convierte la conversación en una ficha por visita. Solo llama entre las 7:00 y las 19:00, espera si el visitador está en otra visita, reintenta a los +5 y +15 min y, si nadie contesta, hace una llamada de cierre a las 18:00.

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
- **Cambiar lo que pregunta el agente** es editar `infra/elevenlabs/prompt.es.md` y correr `elevenlabs-apply`; después `elevenlabs-golden` comprueba que sigue extrayendo bien (7 escenarios: con pedido, sin pedido por competencia o por no necesitar cambiar, dos visitas, visita no realizada, visitador que no puede hablar, datos de paciente e intento de manipulación).
- **Qué se extrae** está en `modules/calls/schema.py` (18 campos; ElevenLabs admite 25 y solo tipos simples). Las visitas adicionales de una llamada viajan juntas como JSON en un campo de texto; si ese JSON viene dañado, la primera ficha se conserva.
- **Resultado**: por webhook firmado (`POST /v1/webhooks/elevenlabs`, opcional) o por consulta directa cada 5 s (siempre activa). Ambos son idempotentes.
- **Probar con tu celular**: `UNO_CALL_PHONE_OVERRIDE=+57…` desvía TODAS las llamadas a ese número (solo desarrollo; el servidor se niega a arrancar en producción con esta variable). Así la cuenta de demostración hace sonar el teléfono de quien prueba. Sin reintentos: `UNO_CALL_RETRY_MINUTES=` (vacío).
- **Privacidad**: el agente no dice el nombre del médico salvo `UNO_CALL_INCLUDE_DOCTOR_NAMES=true` (decisión de legal pendiente). ElevenLabs conserva las conversaciones 30 días (`infra/elevenlabs/agent.json`).

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
