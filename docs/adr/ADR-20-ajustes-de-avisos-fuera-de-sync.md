# ADR-20 · Los ajustes de avisos usan rutas propias, no `/v1/sync`

**Estado:** Aceptada (28 de septiembre de 2026)

## Contexto
La regla «toda escritura del visitador pasa por /v1/sync» (ADR-04) no aplica a lo que exige conexión por naturaleza: registrar una suscripción Web Push o verificar un correo.

## Decisión
`/v1/notifications/*` son rutas en línea, con límites propios (códigos, pruebas, intentos). **Ya implementado.** Las visitas siguen entrando solo por `/v1/sync`.

## Consecuencias
Sin conexión el visitador puede ver sus ajustes pero no cambiarlos. Los avisos SSRF se evitan aceptando solo endpoints HTTPS de servicios de push conocidos.

## Alternativa descartada
Encolar los ajustes como eventos del teléfono.
