# ADR-13 · El objetivo es el valor incremental marginal, no la propensión de compra

**Estado:** Aceptada (28 de septiembre de 2026)

## Contexto
Predecir quién compra premia a quien compraría igual sin visita (doc 03 resumen 2).

## Decisión
Se estima el uplift marginal de la próxima visita, dado el historial. Sin datos de resultados, el sistema usa reglas y *priors* etiquetados como heurísticos (Fase 0).

## Consecuencias
Las recomendaciones se evalúan por valor incremental por hora del visitador. Se exige aleatorización para aprender causalidad.

## Alternativa descartada
Maximizar la probabilidad bruta de compra.
