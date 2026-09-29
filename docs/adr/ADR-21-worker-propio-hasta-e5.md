# ADR-21 · Trabajador de recordatorios propio (asyncio) hasta que lleguen las llamadas

**Estado:** Aceptada (28 de septiembre de 2026)

## Contexto
ADR-05 fija Procrastinate sobre PostgreSQL. Hoy solo hay una tarea periódica (recordatorios) que ya es idempotente por diseño (restricción única en `notification_log`).

## Decisión
Un bucle asíncrono (`uno worker`, o embebido en desarrollo) llama a `run_due_reminders` cada minuto. Se migra a Procrastinate al construir el orquestador de llamadas (E5), sin cambiar `run_due_reminders`. **Ya implementado.**

## Consecuencias
Es una desviación temporal y acotada de ADR-05; el envío es seguro con varios trabajadores a la vez (probado).

## Alternativa descartada
Adoptar Procrastinate ahora, sin necesidad todavía.
