# ADR-16 · El ML (valor) y la optimización (agenda) son componentes separados

**Estado:** Aceptada (28 de septiembre de 2026)

## Contexto
Confundirlos produce un modelo que «aprende rutas» o un solver que decide qué es valioso (doc 03 §15).

## Decisión
El ML entrega valor e incertidumbre por candidato; OR-Tools arma una agenda factible como un problema de orientación con ventanas horarias. Contrato entre ambos.

## Consecuencias
El tiempo y el desplazamiento son del optimizador, no del puntaje.

## Alternativa descartada
Un solo «motor» que puntúa y enruta.
