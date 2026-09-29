# ADR-22 · Ubicación obligatoria y de una sola lectura en Llegué / Terminé

**Estado:** Aceptada (28 de septiembre de 2026) · reemplaza a ADR-06 y a los §9.2 y §9.6 del documento 01

## Contexto
ADR-06 proponía una ventana de «mejor lectura» de 10–15 s en cada toque, una geocerca solo informativa y un permiso de ubicación que, si se negaba, dejaba la app funcionando con un aviso gris. El cliente aclaró el uso real: las visitas son sobre todo en **hospitales urbanos**, no importa la oficina ni el piso, y lo único que se necesita es confirmar dónde está el visitador en un toque, sin tener el GPS encendido todo el tiempo.

## Decisión
1. **Permiso obligatorio.** Sin permiso de ubicación no se entra a la app: `RequireLocation` muestra una pantalla que lo pide, explica que solo se usa en Llegué y Terminé y, si está bloqueado, indica cómo activarlo. Se vuelve a bloquear si el permiso se revoca con la app abierta.
2. **Un toque, una lectura.** Al tocar Llegué o Terminé se pide la posición **una vez** (`getCurrentPosition`, alta precisión, `maximumAge = 0`, tope de 8 s). No hay `watchPosition`, ni ventana de mejor lectura, ni respaldo de baja precisión. El GPS se enciende solo durante esa lectura.
3. **El toque no espera al GPS.** El evento se guarda al instante con la hora del toque (estado `capturing`, que el motor de sincronización no envía) y la ubicación se adjunta cuando llega. Si la app se cierra a medias, al reabrir el toque sale con `location = null`.
4. **Lo que bloquea es el permiso, no la lectura.** Si hay permiso pero la lectura falla (sin señal dentro de un edificio, tiempo agotado), la visita se registra igual y queda `sin_gps`, con «Reintentar ubicación» durante 2 minutos (también para `imprecisa`). Nunca se pierde una visita por el GPS.
5. **Radio por defecto de 300 m** por institución (hospital); 150 m queda para un consultorio independiente. Sigue siendo configurable por institución (`institution.radius_m`) y sigue pendiente de calibrar (pregunta Q6).

## Consecuencias
- Se pierde la ventaja de quedarse con la mejor de varias lecturas: la primera lectura de un teléfono puede ser imprecisa (±100 m o más), sobre todo dentro de edificios. Con radio de 300 m alcanza para verificar «está en el hospital»; si no, el estado es `imprecisa` y el visitador reintenta. Si el piloto mide demasiadas lecturas imprecisas, se reabre esta decisión y se vuelve a la ventana.
- La web no puede forzar el permiso: el usuario puede revocarlo en cualquier momento. Por eso el bloqueo está en la interfaz y, en el servidor, un toque sin ubicación queda marcado `sin_gps` en lugar de rechazarse.
- Quedan fuera por ahora: deshacer, motivo de «lejos», cierre tardío, «Otro médico aquí», adopción automática de referencias y las señales de consistencia avanzadas (doc 02 T4.2–T4.6).

## Alternativas descartadas
- Mantener la ventana de 15 s: el cliente no la necesita y alarga el uso del GPS.
- Rechazar el toque si no hay ubicación: perdería visitas reales dentro de hospitales con mala señal.
- Pedir el permiso solo al primer toque de Llegué: la app se podría usar sin haberlo concedido nunca.
