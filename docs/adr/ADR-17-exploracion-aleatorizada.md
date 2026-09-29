# ADR-17 · La exploración se aleatoriza y registra su probabilidad de selección

**Estado:** Aceptada (28 de septiembre de 2026)

## Contexto
Sin variación aleatoria no se puede estimar el efecto causal de una visita (doc 03 §11, §14).

## Decisión
Cupo de exploración ≤ 15 % con muestreo y `selection_prob` registrada por recomendación.

## Consecuencias
La exploración es la fuente de los datos causales para uplift y *bandits*.

## Alternativa descartada
Un bono de exploración determinista sin registro.
