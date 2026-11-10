# Recuperación de la versión activa del VPS (r33)

Captura: 9 de noviembre de 2026, desde `vmi3469276` (169.58.83.178, novamed.hyperionone.co).
Release activa: `/opt/uno-visitas/releases/20261030-context-r33`. Desde el 30 de octubre
de 2026 a las 14:10 CET no se modificó ningún archivo en `/opt/uno-visitas`.
Antes de esta copia, el repositorio tenía la captura del 6 de octubre (`9802f37`).

## Qué se tomó y dónde quedó

| En el VPS (release r33) | En el repositorio |
|---|---|
| `services/api/src`, `migrations`, `pyproject.toml`, `uv.lock`, `.env.example`, `alembic.ini` | `services/api/` |
| `source/apps/territory` | `apps/territory` |
| `web` (compilado) | `deployments/vps-20261030-r33/web` |
| `infra/elevenlabs`, `infra/web.nginx.conf`, `infra/docker-compose.prod.yml`, `infra/territory.override.yml` | `infra/` |
| `manifest.json`, `build-provenance.json`, Dockerfiles usados | `deployments/vps-20261030-r33/` |

386 archivos coinciden byte a byte con `manifest.json`. Se omitieron `.ruff_cache` y los
planes internos de la entrega (`delta-plan.json`, `demo-delta.json`, `orb-plan.json`).
No se copiaron credenciales (`runtime.env`, `private/`), respaldos ni datos de producción.

## Ajustes propios de esta copia

- `infra/api.Dockerfile` instala `tesseract-ocr` y `tesseract-ocr-spa`. También instala
  `defusedxml` y `reportlab`, porque `uv.lock` no los incluye; el despliegue los instaló aparte.
  Además copia `infra/elevenlabs` en `/opt/uno-voice`.
- `infra/api-requirements.txt` se regeneró desde el `uv.lock` del VPS.
- `infra/web.Dockerfile` usa por defecto `deployments/vps-20261030-r33/web`.
- `pnpm-workspace.yaml` excluye `apps/territory`, que usa npm y su `package-lock.json`.

## Diferencias entre la release y lo que corre

La imagen en ejecución es `uno-visitas-api:context-20261030-r33`. Se construyó desde
`territory-20261016-snc-r16` cambiando solo `modules/calls/service.py`
(`deployments/vps-20261030-r33/api-context-r33.Dockerfile.deployed`).

En el contenedor, `elevenlabs_setup.py` y `modules/calls/schema.py` son anteriores a los de la release.
Las versiones v5 y v6 de esos archivos solo se usaron para publicar el agente en ElevenLabs.
El repositorio guarda las de la release, que coinciden con el agente publicado.
Volver a aplicar la configuración de voz desde el contenedor actual devolvería el agente a la redacción anterior.

## Versiones publicadas desde la captura del 6 de octubre (hora de Colombia)

| Fecha | Versión | Cambio |
|---|---|---|
| 30 oct 08:08 | r33 `context` | La llamada respeta el objetivo editado en la preparación. El pendiente anterior sale de `journey.previous_report`. Es el único cambio de la API desde el 16 oct. |
| 30 oct 07:35 | r32 `juliana-card` | Web antigua: recordatorio confirmado y ficha de visita legible. |
| 29 oct 23:36 | r31 `uno-orb` | Esfera de voz con el nivel real del audio, límite de 4:45, errores sin detalles técnicos, avisos de buzón y de llamada fallida. |
| 29 oct 23:08 | r30 + agente v6 | No vuelve a preguntar lo ya respondido; hace la pregunta de cierre antes de colgar. |
| 29 oct 23:06 | r29 `transcript` | Transcripción en forma de conversación. |
| 28 oct 18:08 | r28 + agente v5 | Sin eco ni relectura; cierre breve. «Prepárate» con copia sin conexión; caché de assets. |
| 28 oct 18:02 | r27 | Sin cargas duplicadas del territorio. |
| 28 oct 18:00 | r26 `availability` | Errores de red claros con «Reintentar», agenda que se refresca cada 30 s, gzip. |
| 26 oct 09:56 | telefonía | Llamadas salientes por troncal SIP. Las 2 pruebas cayeron en buzón: falta verificar una llamada atendida. |
| 23 oct | r22–r25 `demo` | Agente v4 (ESLUX, 285 s, una sola síntesis), orden de visitas en «Prepárate». |
| 15–16 oct | 27 versiones | Territorio (mapa, rutas OSRM, planificación), paneles, marketing, flujos de trabajo, voz en el navegador, catálogo SNC. |

## Límites

- La web antigua sigue sin fuente TypeScript que la reproduzca.
- `uv.lock` no está sincronizado con `pyproject.toml` (faltan `defusedxml` y `reportlab`).
- En `apps/territory`, `package-lock.json` no incluye `@elevenlabs/client`, así que `npm ci` falla.
  Hay que usar `npm install`. La prueba `BrowserVoice.test.tsx` necesita `jsdom`, que no está en
  `devDependencies`. Con eso (9 nov): `tsc` y `vite build` pasan, el CSS compilado coincide con el
  publicado (`index-BzQtGHza.css`) y pasan las 6 pruebas. Los bundles JS salen con otro hash,
  porque se resolvieron versiones de dependencias distintas.
- Las pruebas de `services/api/tests` son de la captura del 6 de octubre y no cubren los módulos nuevos.
  Con esta copia (9 nov) pasan 366 y fallan 31, todas sobre llamadas y reportes
  (`test_call_reminders`, `test_calls`, `test_calls_schema`, `test_pilot`, `test_reports`).
  Esos archivos esperan el comportamiento de octubre: varias visitas por llamada y los campos
  anteriores del agente. Con el mismo entorno, el código del 6 de octubre falla 59 veces en esos
  mismos archivos, así que estas fallas no se deben a la copia.
- La OSRM (`uno-territory-osrm`) y la biblioteca `/opt/uno-visitas/territory/source-library`
  viven fuera de la release y no se copiaron.
