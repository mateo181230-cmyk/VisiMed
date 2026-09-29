# Registro de decisiones de arquitectura

Las ADR-01 a ADR-11 están en el documento 01 §20 (`Plan UNO Visitas/`). Las siguientes se aprobaron el 28 de septiembre de 2026 (documento 03 §2.2) y se guardan aquí, una por archivo.

| ADR | Decisión | Estado en el código |
| --- | --- | --- |
| [ADR-12](ADR-12-unidad-medico-linea.md) | La unidad de aprendizaje es médico × línea | Implementada (esquema) |
| [ADR-13](ADR-13-valor-incremental.md) | El objetivo es el valor incremental marginal, no la propensión de compra | Diseño (Fase 0 pendiente) |
| [ADR-14](ADR-14-bitacora-dominio.md) | Bitácora de dominio append-only con doble marca de tiempo | Implementada |
| [ADR-15](ADR-15-extraccion-propia.md) | Extracción enriquecida propia, asíncrona, tras la interfaz `Extractor` | Diseño (E11-A) |
| [ADR-16](ADR-16-ml-vs-optimizacion.md) | El ML (valor) y la optimización (agenda) son componentes separados | Diseño (Fase 0b) |
| [ADR-17](ADR-17-exploracion-aleatorizada.md) | La exploración se aleatoriza y registra su probabilidad de selección | Diseño (Fase 0b) |
| [ADR-18](ADR-18-fases-por-datos.md) | Cada fase de ML se abre por una compuerta de datos medible, no por una fecha | Vigente |
| [ADR-19](ADR-19-worker-ml-aislado.md) | El trabajo de ML corre en una cola y un worker propios | Diseño |
| [ADR-20](ADR-20-ajustes-de-avisos-fuera-de-sync.md) | Los ajustes de avisos usan rutas propias, no `/v1/sync` | Implementada |
| [ADR-21](ADR-21-worker-propio-hasta-e5.md) | Trabajador de recordatorios propio (asyncio) hasta que lleguen las llamadas | Implementada |
| [ADR-22](ADR-22-ubicacion-obligatoria-un-toque.md) | Ubicación obligatoria y de una sola lectura en Llegué / Terminé (reemplaza ADR-06) | Implementada (teléfono) |
| [ADR-23](ADR-23-llamadas-elevenlabs-telyaco-cola-propia.md) | Llamadas con ElevenLabs sobre Telyaco; cola en tablas propias, sin Procrastinate | Implementada (servidor); falta probar con una llamada real |
| [ADR-24](ADR-24-entrenar-medico-virtual-tavus.md) | Entrenar: práctica con médico virtual (Tavus + voz de ElevenLabs) como módulo de UNO, contenido como código y evaluación propia | Implementada (servidor y app); falta una conversación real (Tavus sin créditos) |
