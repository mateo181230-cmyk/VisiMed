# ADR-24 · Entrenar: práctica con médico virtual dentro de UNO

**Estado:** Aceptada e implementada (29 de septiembre de 2026). Propuesta en el documento 04 §11 (`Plan UNO Visitas/`). El médico real espera créditos de Tavus (D1 del documento 04).

## Contexto
Novamed quiere que los visitadores practiquen la visita de ESOMED antes de hacerla en la calle. Había un PRD de Training como producto aparte y un prototipo en Sangil (`esomed-bot-doctor`): médico en video de Tavus, pensado para computador y muy gamificado (mapa de niveles, orbes, trofeos). UNO Visitas ya tiene usuarios, roles, servidor, trabajador, bitácora y secretos fuera de OneDrive. La cuenta de Tavus es **compartida** con otros proyectos (Jetour, Mafe) y hoy no tiene créditos de conversación.

## Decisión
1. **Es un módulo de UNO, no otra app.** API `modules/training` (rutas `/v1/training`, `/v1/manager/training`, webhook `/v1/webhooks/tavus/{token}`) y pestaña **Entrenar** en la PWA (`features/training`). Mismo ingreso, roles y base de datos: el avance queda guardado por visitador.
2. **Un médico virtual = un PAL de Tavus por versión de escenario**, con cara de Tavus, **voz de ElevenLabs en la capa TTS** (`tts_engine: "elevenlabs"`, voces públicas sin llave) y LLM `tavus-gemma-4`. El prompt se compila desde el contenido; ninguna regla vive solo en Tavus.
3. **Contenido como código** en `services/api/src/uno/modules/training/content/` (escenarios, lección, formulario, banco de mensajes aprobados con su fuente). Va dentro del paquete porque la imagen de la API solo copia `services/api`. Cambiar un médico es editar el JSON y correr `uno training-apply`.
4. **Publicación segura en la cuenta compartida.** Solo se crean o borran PAL cuyo nombre empieza por `UNO Entrenar`; el nombre lleva la huella del contenido, así que publicar lo mismo desde otra base de datos **reutiliza** el PAL en vez de duplicarlo. `training-cleanup` solo borra versiones retiradas sin prácticas vivas.
5. **Proveedor detrás de una interfaz** (`ConversationProvider`) con modos `off` (por defecto), `fake` (médico simulado, sin video, para desarrollo y pruebas) y `tavus`, como las llamadas (ADR-23).
6. **Disponibilidad antes de empezar.** Al abrir Entrenar, el servidor pregunta a Tavus con una conversación en `test_mode` (sin costo; se borra enseguida), como mucho cada 5 minutos. Sin créditos, la app dice «no disponible por ahora», no pide el micrófono y deja hacer la preparación y el formulario.
7. **H1 evalúa, no Tavus.** Hoy: reglas deterministas (puerto fiel del prototipo) presentadas como **calificación preliminar**; la «mejor respuesta» sale solo del banco aprobado. Después: juez LLM con salida validada por esquema (D3). La transcripción llega por webhook con un token por intento o, sin URL pública, por consulta cada 5 s; ambos caminos son idempotentes.
8. **Sin elementos de juego.** Lista de escenarios con estado (Sin practicar, Practicado, Aprobado), práctica sugerida, sin bloqueos, trofeos, puntos ni animaciones. El resultado usa la rúbrica de Novamed (6 competencias × 5) y la diferencia frente al intento anterior.
9. **Privacidad.** Consentimiento versionado antes de la primera visita; la cámara del visitador no se usa (D7); la transcripción vive en `practice_turn` y **nunca** en `domain_event`; tope de prácticas por día y de minutos por visita.

## Consecuencias
- Se reutilizan auth, roles, bitácora, trabajador y despliegue; la migración 0004 agrega seis tablas.
- La práctica depende de la red y el costo es por minuto de Tavus; hasta que haya créditos, el módulo muestra la preparación pero no la visita.
- La calificación por reglas sola no alcanza la barra del Anexo (el diálogo «regular» da 7/30 y debería caer en 14–19): por eso se muestra como preliminar hasta tener el juez.
- Los umbrales de aprobación por escenario (18/20/22/24 más mínimos por competencia) vienen del prototipo y son **PROPUESTA** hasta que Novamed decida (D9).

## Alternativas descartadas
- App aparte en Next.js (la del prototipo): duplica ingreso, usuarios y despliegue.
- Agente de voz de ElevenLabs sin video: más barato, pero el PRD pide médico en video; queda como plan B si Tavus falla en redes móviles.
- Evaluar dentro de Tavus (*post-call actions*): no es reproducible ni auditable por H1.
- Descubrir la falta de créditos al tocar «Empezar visita»: el visitador daba permisos y aceptaba condiciones para nada.
