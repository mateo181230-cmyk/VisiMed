# ADR-14 · Bitácora de dominio append-only con doble marca de tiempo

**Estado:** Aceptada (28 de septiembre de 2026)

## Contexto
`sync_event` es transporte del teléfono; no cubre llamadas, extracciones ni recomendaciones. Hay que reconstruir qué sabía el modelo en cada momento (doc 03 §5).

## Decisión
Tabla `domain_event` con `occurred_at` y `recorded_at`, emitida en la misma transacción que el cambio de estado. Sin nombres, coordenadas, teléfonos ni transcripciones en el payload (lo verifica `events.emit`). En PostgreSQL la migración instala disparadores que impiden `UPDATE`/`DELETE` (y en `sync_event` solo permiten cambiar `status` y `reason`). **Ya implementado.**

## Consecuencias
Cada cambio de agenda deja su evento. El perfil futuro se calcula como pliegue de eventos.

## Alternativa descartada
Reconstruir desde tablas mutables.
