# Contrato de eventos de sincronización

Es el único camino de escritura del visitador (`POST /v1/sync`, doc 01 §10). Los nombres de evento son los de la bitácora de dominio (doc 03 §5.2); reemplazan a los nombres en español del doc 01 §10.2:

| Doc 01 §10.2 | Evento |
| --- | --- |
| `visita.agendada` | `visit_scheduled` |
| `visita.reprogramada` | `visit_rescheduled` |
| `visita.no_realizada` | `visit_not_done` |
| `medico.creado` | `doctor_created` |
| `visita.llegue` · `visita.termine` | `visit_arrived` · `visit_finished` |
| (nuevo, E4) reintento de ubicación | `visit_location_retried` |
| (nuevo, E5/E6) confirmar la ficha · corregir un dato | `report_confirmed` · `report_field_edited` |

## Petición

```json
POST /v1/sync   (Authorization: Bearer …)
{
  "device_id": "uuid del teléfono (nace en el teléfono)",
  "sent_at": "2026-09-29T14:35:00Z",
  "outbox_pending": 12,
  "events": [ /* ≤ 100, en cualquier orden: el servidor aplica por device_ts */ ]
}
```

Evento:

```json
{
  "event_id": "UUIDv7 — clave de idempotencia",
  "type": "visit_scheduled",
  "visit_id": "UUIDv7 de la visita (null en doctor_created)",
  "device_ts": "hora del toque, ISO 8601 con zona",
  "app_version": "0.1.0",
  "payload": { }
}
```

## Respuesta

```json
{ "server_time": "…", "clock_skew_s": 0,
  "results": [ { "event_id": "…", "status": "applied | duplicate | rejected", "reason": "…" } ] }
```

- `applied`: se aplicó ahora. `duplicate`: ya estaba aplicado (reenviar es seguro). `rejected`: inválido para el estado actual; **no se reintenta** y no detiene el lote.
- Un evento `received` que quedó a medias (caída del servidor) se vuelve a intentar al reenviarlo.
- `clock_skew_s` es `sent_at − hora del servidor`; > 600 s se marca como reloj desfasado.

## Eventos

### `doctor_created`
`payload`: `doctor_id` (uuid), `full_name` (2–160), `specialty?`, `default_line_id` (uuid), y **una** de: `institution_id` (existente) o `institution: {id, name, address?, city?}` (nueva).
Crea el médico (`pending_review`) y lo añade al panel del visitador. Reenviar el mismo `doctor_id` es idempotente si ya es suyo; si pertenece a otro visitador → `doctor_id_conflict`.

### `visit_scheduled`  (`visit_id` obligatorio)
`payload`: `doctor_id` (debe estar en su panel), `line_ids` (1–2, activas; la primera es la principal), `scheduled_at` (ISO con zona), `planned_by?` (`rep` | `spontaneous`).
El mismo `visit_id` con los mismos datos es idempotente; con otros datos → `visit_id_conflict`.

### `visit_rescheduled`  (`visit_id` obligatorio)
`payload`: `scheduled_at`. Solo si la visita está `scheduled` (la evidencia de una visita iniciada es inmutable) → si no, `visit_not_editable`.

### `visit_not_done`  (`visit_id` obligatorio)
`payload`: `reason` ∈ `doctor_unavailable | cancelled_by_office | rescheduled | other`. Solo desde `scheduled`. El mismo motivo repetido es idempotente.

### Llegué / Terminé y ubicación (módulo E4)

Un solo toque y **una** lectura de ubicación por momento. El permiso de ubicación es obligatorio en el teléfono, pero **nunca se pierde una visita por falta de GPS**: si no hubo lectura se envía `location: null` y el evento se acepta con estado `sin_gps` (ver abajo). Las coordenadas se guardan solo en la tabla `visit`; la bitácora de dominio no admite `lat`/`lng` (`events.FORBIDDEN_KEYS`).

**Objeto `location`** (o `null` si no hubo lectura):

```json
{ "lat": 4.6765,            // −90 … 90
  "lng": -74.0481,          // −180 … 180
  "precision_m": 12.5,      // ≥ 0
  "fix_ts": "2026-09-29T14:35:02Z",   // ISO 8601 con zona: cuándo se tomó la lectura
  "source": "gps" }         // "gps" | "reused"
```

Campos de diagnóstico opcionales en el payload (van **solo** al evento de dominio, no a columnas): `permission` (`granted` | `denied` | `prompt`), `duration_ms` (entero ≥ 0) y `error` (texto corto o `null`; si pasa de 120 caracteres se recorta, no se rechaza).

#### `visit_arrived`  (`visit_id` obligatorio)
`payload`: `{ location: Location | null, permission?, duration_ms?, error? }`.
La visita debe ser del visitador (`unknown_visit`) y estar `scheduled` → pasa a `in_progress`; con cualquier otro estado → `visit_not_editable`. Guarda `arrived_at` = `device_ts` (la hora del toque), la ubicación y el estado de geocerca.

#### `visit_finished`  (`visit_id` obligatorio)
Mismo payload. Desde `in_progress` → `finished`. **También** se acepta desde `scheduled` («Terminé» sin «Llegué»): la visita queda `finished` con `arrived_at` nulo, y esa es la señal «sin llegada» (no hay columna de banderas). Con cualquier otro estado → `visit_not_editable`. Guarda `finished_at` = `device_ts`.

#### `visit_location_retried`  (`visit_id` obligatorio)
`payload`: `{ moment: "arrival" | "finish", location: Location, permission?, duration_ms? }` (la ubicación es obligatoria).
Reemplaza la ubicación de ese momento y recalcula su estado. Reglas, en este orden:

1. la visita es del visitador → si no, `unknown_visit`;
2. el toque de ese momento existe (`arrived_at` / `finished_at` no nulo) → si no, `visit_not_editable`;
3. el estado actual de ese momento es `sin_gps` o `imprecisa` → si no, `location_not_retryable`;
4. `device_ts − hora del toque ≤ 2 minutos` → si no, `retry_window_expired`.

#### Estado de geocerca
Se calcula al aplicar el evento contra la referencia de la institución de la visita (`institution.lat`, `.lng`, `.radius_m`; radio por defecto **300 m**). No se recalcula si la referencia cambia después. Es la misma regla que corre en el teléfono; ambos pasan los 20 casos de `docs/contratos/geocerca-casos.json`. Orden de decisión:

| # | Condición | Estado | `distance_m` |
| --- | --- | --- | --- |
| 1 | sin lectura (`location: null`) | `sin_gps` | `null` |
| 2 | `precision_m > 100` | `imprecisa` | entera si hay referencia, si no `null` |
| 3 | sin referencia (visita sin institución, o institución sin `lat`/`lng`) | `sin_referencia` | `null` |
| 4 | `distance_m − precision_m ≤ radius_m` | `verificada` | entera |
| 5 | en otro caso | `lejos` | entera |

`distance_m` es la distancia haversine (radio terrestre 6 371 000 m) redondeada a entero con la mitad hacia arriba (`floor(x + 0.5)`) y se compara **ya redondeada**.

**Bitácora de dominio.** Cada evento aplicado emite `visit_arrived` / `visit_finished` / `visit_location_retried` con `geo_state`, `distance_m`, `precision_m`, `location_source`, `fix_ts` y los diagnósticos (`permission`, `duration_ms`, `error`); `visit_finished` añade `without_arrival` y `visit_location_retried` añade `moment` y `previous_geo_state`. **Sin coordenadas.**

## Motivos de rechazo (`reason`)

`unknown_event_type` · `invalid_payload` · `visit_id_required` · `unknown_visit` · `unknown_doctor` · `unknown_line` · `unknown_institution` · `institution_ambiguous` · `duplicate_line` · `invalid_time` (±2 años) · `visit_not_editable` · `location_not_retryable` · `retry_window_expired` · `visit_id_conflict` · `doctor_id_conflict` · `event_id_conflict`.

## Bajada de estado

`GET /v1/me/state?cursor=N` → `{ server_time, cursor, full, timezone, lines, products, institutions, doctors, visits, reports, config }`. Sin cursor, con cursor ≤ 0 o mayor que el del servidor, devuelve el estado **completo**: todas las visitas y reportes propios, el panel actual y los médicos e instituciones referenciados por esas visitas, incluido el historial y las citas lejanas. Con un cursor válido, devuelve lo que cambió (`change_seq > N`) y las dependencias de las visitas devueltas. El teléfono guarda `cursor` y lo envía en la siguiente llamada.

`config.window_past_days` y `window_future_days` conservan la sugerencia de presentación de −7 a +14 días por compatibilidad; no recortan el estado completo. Así, reinstalar la app o actualizar IndexedDB no elimina el historial visible ni las citas fuera de esa ventana.

Campos de `visits[]` agregados por E4:

```json
{ "arrived_at": "2026-09-29T14:35:00Z | null",
  "finished_at": "… | null",
  "arrival_geo": { "state": "verificada", "distance_m": 100, "precision_m": 12.5 },   // null si no hay llegada
  "finish_geo":  { "state": "sin_gps",    "distance_m": null, "precision_m": null } } // null si no hay cierre
```

`state` ∈ `verificada | lejos | imprecisa | sin_referencia | sin_gps`. **No se envían lat/lng** al teléfono. `institutions[].radius_m` es 300 por defecto; una referencia fijada por un administrador (`uno set-institution-ref`) baja al teléfono como cualquier otro cambio de institución.

## Orden y conflictos

- Dentro de un lote, los eventos se aplican por `device_ts` (estable): cualquier permutación o duplicación da el mismo estado final (pruebas de propiedades en `tests/test_sync_agenda.py` y, para llegué/terminé, en `tests/test_llegue_termine.py`).
- Entre lotes, el teléfono envía en orden y con un candado (un solo envío a la vez).
- Cada evento aplicado emite su evento de dominio en la misma transacción (`domain_event`).

### `report_confirmed`  (`visit_id` obligatorio)
`payload`: `{}`. El visitador da por buena la ficha de la llamada. La ficha pasa a `confirmed` y la visita a `confirmed`. Reenviarlo es seguro. Sin ficha → `no_report`; visita de otro visitador → `unknown_visit`.

### `report_field_edited`  (`visit_id` obligatorio)
`payload`: `field` (uno de `interest_level`, `visit_outcome`, `order_taken`, `no_order_reason`, `objection`, `competitor`, `commitment`, `next_action`, `territory_signal`, `summary`) y `value` (`null` o texto vacío borra el dato).
El valor queda con `source = "rep_edit"` y confianza alta; **una nueva extracción de la llamada nunca lo pisa**. Se puede corregir también una ficha ya confirmada. Un valor fuera del vocabulario o del rango → `invalid_value`. La bitácora de dominio registra qué campo cambió, nunca el texto escrito.

## Fichas en la bajada de estado

`GET /v1/me/state` incluye `reports[]` (una ficha por visita: `status` `ready | confirmed`, `complete`, `fields{campo: {value, confidence, source}}`) y, en cada visita, `call` con la llamada de resumen viva (`status` `queued | dialing`, `attempt`, `next_at`, `reason`) para mostrar «te llamamos de nuevo a las 10:20». Son incrementales por `change_seq`, como el resto. Al subir de versión la base local del teléfono se descarta el cursor y se baja todo de nuevo.
