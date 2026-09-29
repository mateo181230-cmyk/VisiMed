# ADR-12 · La unidad de aprendizaje es médico × línea

**Estado:** Aceptada (28 de septiembre de 2026)

## Contexto
Un puntaje único por médico (`doctor_score`) esconde que el mismo médico puede comprar mucho de una línea y nada de otra (doc 03 §6).

## Decisión
El perfil tiene tres niveles: `doctor_profile`, `doctor_line_profile` (el central) y, cuando sea identificable, `doctor_line_rep_profile`. La línea de producto es una dimensión de primer nivel: tabla `product_line` y relación `visit_line`. **Ya implementado** en el esquema (`product_line`, `visit_line`, `visit.primary_line_id`).

## Consecuencias
Ningún `doctor_score` único. Toda visita lleva su línea. Agendar exige elegir línea (por defecto, la del médico).

## Alternativa descartada
Un puntaje por médico.
