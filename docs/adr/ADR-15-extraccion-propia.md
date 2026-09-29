# ADR-15 · Extracción enriquecida propia, asíncrona, tras la interfaz `Extractor`

**Estado:** Aceptada (28 de septiembre de 2026)

## Contexto
El *data collection* de ElevenLabs admite ≤ 25 campos simples; el aprendizaje exige listas por producto con valor, confianza y procedencia (doc 03 §7).

## Decisión
ElevenLabs entrega la tarjeta de 12 campos; UNO corre una segunda etapa propia sobre la transcripción, sin bloquear la tarjeta.

## Consecuencias
Nuevo subencargado del tratamiento (proveedor de LLM). Exige decisión legal (Q-I9) y de proveedor (Q-I10).

## Alternativa descartada
Todo dentro del *data collection* de ElevenLabs.
