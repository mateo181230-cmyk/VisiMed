# ADR-24 · Entrenar: práctica con médico virtual dentro de UNO

**Estado:** Aceptada e implementada (29 de septiembre de 2026). Propuesta en el documento 04 §11 (`Plan UNO Visitas/`). Disponibilidad de Tavus comprobada con la nueva credencial en `test_mode`; el usuario confirmó la entrada y reproducción del médico en Chrome para Android (30 de septiembre). Pendiente medir la calidad del video recibido y validar una visita completa con evaluación.

## Contexto
Novamed quiere que los visitadores practiquen la visita de ESOMED antes de hacerla en la calle. Había un PRD de Training como producto aparte y un prototipo en Sangil (`esomed-bot-doctor`): médico en video de Tavus, pensado para computador y muy gamificado (mapa de niveles, orbes, trofeos). UNO Visitas ya tiene usuarios, roles, servidor, trabajador, bitácora y secretos fuera de OneDrive. La cuenta inicial de Tavus era **compartida** con otros proyectos (Jetour, Mafe) y no tenía créditos de conversación al verificarla el 29 de septiembre.

## Decisión
1. **Es un módulo de UNO, no otra app.** API `modules/training` (rutas `/v1/training`, `/v1/manager/training`, webhook `/v1/webhooks/tavus/{token}`) y pestaña **Entrenar** en la PWA (`features/training`). Mismo ingreso, roles y base de datos: el avance queda guardado por visitador.
2. **Un médico virtual = un PAL de Tavus por versión de escenario**, con cara de Tavus, **voz de ElevenLabs en la capa TTS** (`tts_engine: "elevenlabs"`, voces públicas sin llave) y LLM `tavus-gemma-4`. El prompt se compila desde el contenido; ninguna regla vive solo en Tavus.
3. **Contenido como código** en `services/api/src/uno/modules/training/content/` (escenarios, lección, formulario, banco de mensajes aprobados con su fuente). Va dentro del paquete porque la imagen de la API solo copia `services/api`. Cambiar un médico es editar el JSON y correr `uno training-apply`.
4. **Publicación segura en la cuenta compartida.** Solo se crean o borran PAL cuyo nombre empieza por `UNO Entrenar`; el nombre lleva la huella del contenido, así que publicar lo mismo desde otra base de datos **reutiliza** el PAL en vez de duplicarlo. La referencia local también debe existir en la cuenta actual: al cambiar de cuenta o retirar un PAL, `training-apply` publica una versión nueva. `training-cleanup` solo borra versiones retiradas sin prácticas vivas.
5. **Proveedor detrás de una interfaz** (`ConversationProvider`) con modos `off` (por defecto), `fake` (médico simulado, sin video, para desarrollo y pruebas) y `tavus`, como las llamadas (ADR-23).
6. **Disponibilidad antes de empezar.** Al abrir Entrenar, el servidor pregunta a Tavus con una conversación en `test_mode` (sin costo; se borra enseguida), como mucho cada 5 minutos. Sin créditos, la app dice «no disponible por ahora», no pide el micrófono y deja hacer la preparación y el formulario.
7. **H1 evalúa, no Tavus.** Hoy: reglas deterministas (puerto fiel del prototipo) presentadas como **calificación preliminar**; la «mejor respuesta» sale solo del banco aprobado. Después: juez LLM con salida validada por esquema (D3). La transcripción llega por webhook con un token por intento o, sin URL pública, por consulta cada 5 s; ambos caminos son idempotentes.
8. **Sin elementos de juego.** Lista de escenarios con estado (Sin practicar, Practicado, Aprobado), práctica sugerida, sin bloqueos, trofeos, puntos ni animaciones. El resultado usa la rúbrica de Novamed (6 competencias × 5) y la diferencia frente al intento anterior.
9. **Privacidad.** Consentimiento versionado antes de la primera visita; la cámara del visitador no se usa (D7); la transcripción vive en `practice_turn` y **nunca** en `domain_event`; tope de prácticas por día y de minutos por visita.

## Consecuencias
- Se reutilizan auth, roles, bitácora, trabajador y despliegue; la migración 0004 agrega seis tablas.
- La práctica depende de la red y el costo es por minuto de Tavus; cuando falten créditos, el módulo muestra la preparación pero no la visita.
- La calificación por reglas sola no alcanza la barra del Anexo (el diálogo «regular» da 7/30 y debería caer en 14–19): por eso se muestra como preliminar hasta tener el juez.
- Los umbrales de aprobación por escenario (18/20/22/24 más mínimos por competencia) vienen del prototipo y son **PROPUESTA** hasta que Novamed decida (D9).

## Verificación del cambio de cuenta (30 de septiembre de 2026)
- Se guardó la nueva credencial en `~/.uno-visitas/secrets.env`, fuera del repositorio y de OneDrive, y se reinició la API local.
- Los cuatro escenarios quedaron publicados como v2 en la nueva cuenta. No había prácticas activas durante el cambio.
- `training-check` confirmó que Tavus acepta conversaciones en `test_mode`, sin consumo de créditos; esta prueba no conecta al médico ni comprueba voz o video.
- Pasaron las 54 pruebas del servidor para Entrenar, incluida una regresión que cambia de cuenta, conserva las versiones anteriores y verifica que una segunda publicación no duplica médicos.
- En esa verificación inicial no se pudo hacer el recorrido del navegador: el PIN original de la cuenta de demostración ya no coincidía con el guardado. No se modificó ese PIN. La validación posterior en el teléfono se registra abajo.

## Corrección de la conexión móvil (30 de septiembre de 2026)
- La revisión de llamadas reales encontró sesiones cerradas con `participant_absent_timeout`: Tavus había conectado al médico, pero el navegador no había ingresado. La carga del cliente y su motor WebRTC ahora ocurre antes de crear la conversación; la pantalla de la visita reutiliza esa instancia.
- La precarga tiene un máximo de 15 segundos y la entrada a la sala/recepción de medios, 30 segundos. Los fallos permiten volver a conectar en la misma sala. Se recuperan también pistas de un médico ya conectado y se ofrece activar el audio si el navegador exige un toque.
- El cliente de Daily se incluye en la caché de la PWA para evitar que una versión instalada pierda su importación diferida al actualizar el despliegue. La videollamada sigue requiriendo red.
- El video conserva su proporción y llena verticalmente el espacio entre el nombre y los controles, recortando los lados. «Ver completo» permite recuperar el cuadro horizontal sin volver a conectar ni modificar el flujo de medios. La foto solo se oculta cuando el video empieza a reproducirse.
- Pasaron las 232 pruebas de la app y la compilación de producción. La prueba del cliente real en una sala gratuita, sin micrófono ni médico, entró en unos 2,5 segundos; este tiempo no mide una conversación real en el teléfono.
- El usuario confirmó que el médico aparece y se escucha en Chrome para Android, y que cargó mucho más rápido. Solicitó después el encuadre vertical; este se comprobó visualmente en tamaños de 390 × 844 y 360 × 640. La nitidez del video real en ese encuadre y el recorrido completo hasta la evaluación requieren validación adicional.

## Alternativas descartadas
- App aparte en Next.js (la del prototipo): duplica ingreso, usuarios y despliegue.
- Agente de voz de ElevenLabs sin video: más barato, pero el PRD pide médico en video; queda como plan B si Tavus falla en redes móviles.
- Evaluar dentro de Tavus (*post-call actions*): no es reproducible ni auditable por H1.
- Descubrir la falta de créditos al tocar «Empezar visita»: el visitador daba permisos y aceptaba condiciones para nada.
