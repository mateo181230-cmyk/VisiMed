# ADR-18 · Cada fase de ML se abre por una compuerta de datos medible, no por una fecha

**Estado:** Aceptada (28 de septiembre de 2026)

## Contexto
Con 3 visitadores y ≈ 450–900 visitas no se puede entrenar nada honesto (doc 03 §10, §22). **Novamed confirmó (28 sep 2026) que no existen datos históricos comerciales:** la base se construye desde el uso.

## Decisión
Fase 0 (reglas y *priors*) hasta cumplir las compuertas. Los resultados comerciales de aprendizaje serán L0/L1 capturados por la propia app y la llamada.

## Consecuencias
El producto declara a qué nivel aprendió cada modelo y nunca afirma ventas incrementales sin datos de ventas.

## Alternativa descartada
Calendario fijo de modelos.
