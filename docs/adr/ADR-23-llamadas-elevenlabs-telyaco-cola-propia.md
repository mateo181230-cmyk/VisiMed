# ADR-23 · Llamadas con ElevenLabs sobre Telyaco y cola en tablas propias

**Estado:** Aceptada (28 de septiembre de 2026). Sustituye al «motor de llamadas de H1» del PRD, a ADR-07 en su parte del proveedor y a lo que ADR-21 anunciaba sobre migrar a Procrastinate.

## Contexto
El cliente eligió un número de **Telyaco** (troncal SIP) y **ElevenLabs Agents** para la voz, la transcripción y el resumen. La cuenta de ElevenLabs es **compartida con otras campañas** (Coopfuturo, Defensores de la Patria): los nueve números de Telyaco ya estaban asignados a esos agentes.
ADR-05/ADR-21 preveían Procrastinate al llegar las llamadas. Pero el desarrollo y las pruebas rápidas corren en SQLite y Procrastinate exige PostgreSQL; además el volumen es mínimo (~900 llamadas en 3 semanas) y todo el estado que importa ya vive en tablas.

## Decisión
1. **Proveedor detrás de una interfaz** (`VoiceProvider`): `ElevenLabsProvider` (real), `FakeProvider` (pruebas y desarrollo, mismo contrato). `UNO_CALL_BACKEND=off` es el valor por defecto: nunca se llama a nadie por accidente.
2. **La cola son las tablas** `call` y `call_visit`: cada llamada tiene estado, intento y `scheduled_for`; el trabajador reclama con `UPDATE … WHERE status='queued'` (atómico) y un índice único parcial impide que una visita esté en dos llamadas vivas. Sirve igual en SQLite y PostgreSQL; sin Redis ni Procrastinate.
3. **El agente vive en el repositorio** (`infra/elevenlabs/`: guion, voz, turnos, escenarios) y se aplica por API con `uno elevenlabs-apply`. Los 18 campos que se extraen salen de `modules/calls/schema.py`, la misma definición que valida lo recibido.
4. **Resultado por dos vías**: webhook firmado (HMAC) y consulta directa cada pocos segundos. El webhook es opcional; con la consulta basta para operar. Ambos son idempotentes.
5. **Seguridad en una cuenta compartida**: solo se crea o actualiza el agente con el nombre de UNO; un número asignado a otro agente **no se reasigna** sin `--force-reassign`; el agente limita sus llamadas simultáneas (3) y no usa ráfagas; fuera de producción solo se llama a celulares de `UNO_CALL_ALLOWED_PHONES`.
6. **Privacidad**: el nombre del médico solo viaja a ElevenLabs si `UNO_CALL_INCLUDE_DOCTOR_NAMES=true` (por defecto no; decisión de legal, Q15). Nunca viajan pacientes, documentos ni celulares de médicos.

## Consecuencias
- La ficha (`visit_report`) guarda el valor, la confianza y quién lo escribió; una corrección del visitador nunca la pisa la llamada.
- Un tiempo agotado justo al marcar puede, en el peor caso, repetir una llamada (la API de ElevenLabs no tiene llave de idempotencia). Se acepta: es una molestia, no un daño.
- Si el volumen crece, la cola pasa a Procrastinate sin cambiar `handle_result` ni el proveedor.

## Alternativas descartadas
- Procrastinate ahora: PostgreSQL obligatorio en desarrollo y una dependencia más sin necesidad.
- Extraer con un LLM propio desde el día 1: el análisis de ElevenLabs sacó los campos con exactitud en el banco de escenarios; queda como plan B (ADR-15).

## Actualización (29 de septiembre de 2026): el número pasa de Telyaco a Twilio

**Motivo.** El único intento real por el troncal de Telyaco (`sip.voipcentral.net`, PortaSIP) fue autenticado (401 → INVITE con credenciales → 100 Trying → 183 Early Media) y doce segundos después rechazado con `403 Auth Failed` sin más detalle. El motivo solo lo puede ver Telyaco (número de origen sin habilitar, saldo o restricción de destino) y comparte troncal con campañas en producción de otro proyecto.

**Decisión del cliente.** Usar **Twilio**, sin tocar el número colombiano existente (+57 601 3285121). El resto de esta ADR no cambia: ElevenLabs sigue poniendo la voz y el agente; solo cambia quién lleva la llamada hasta el celular.

**Cambios en el código.**
- `ElevenLabsProvider` detecta si el número de la cuenta es `twilio` o `sip_trunk` (una consulta la primera vez; se puede fijar con `UNO_ELEVENLABS_PHONE_CHANNEL`) y usa el endpoint que corresponde: `/v1/convai/twilio/outbound-call` o `/v1/convai/sip-trunk/outbound-call`. El cuerpo es el mismo; la respuesta trae `callSid` en vez de `sip_call_id`.
- Todo lo demás (orquestador, reintentos, fichas, webhook) es igual: no depende del operador.

**Consecuencias.**
- Un número de EE. UU. se ve en el celular del visitador como +1 …; a largo plazo conviene un número colombiano (Twilio lo permite con el paquete regulatorio que ya tiene la cuenta).
- Con Twilio, «Marca a UNO» (línea entrante) queda soportado de forma nativa por ElevenLabs.
- Para llamar a Colombia hay que activar el permiso geográfico de voz de Twilio para ese país y, si la cuenta es de prueba, verificar el celular de destino.
- Los números de Twilio quedan enlazados a **un** espacio de trabajo de ElevenLabs a la vez: importarlos en el de UNO los desvincula del anterior.

**Verificado (29 de septiembre de 2026).** Primera llamada real por Twilio (+1 570 776 9534 → celular en Colombia, agente de UNO): 113 s, el visitador respondió en lenguaje natural con muletillas y frases cortadas y las seis preguntas se hicieron saltando las ya contestadas. La ficha salió correcta en todos los campos (interés 3, pedido sí, objeción, próximo paso a 7 días con fecha calculada, sin competidor identificado). Un primer intento minutos antes quedó como «buzón» porque del lado del celular solo llegó silencio (dos turnos «…»); desde entonces el silencio o el ruido ya no cuenta como que la persona habló.
