# ADR-19 · El trabajo de ML corre en una cola y un worker propios

**Estado:** Aceptada (28 de septiembre de 2026)

## Contexto
La llamada debe salir en < 60 s; un entrenamiento no puede competir con ella (doc 03 §3.5).

## Decisión
Cola `ml` con concurrencia 1 y límites de CPU. Aún no hay trabajos de ML; se decide al llegar la Fase 0.

## Consecuencias
Nunca comparte cola con las llamadas.

## Alternativa descartada
Compartir la cola de llamadas.
