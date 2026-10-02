# Correcciones verificadas el 2 de octubre de 2026

Rama: `integracion/pendientes-y-entrenar-v2`.

## Cambios

- Una sincronización completa conserva todas las visitas y reportes propios, con sus
  médicos y sedes históricas. Los errores HTTP de infraestructura conservan los eventos
  pendientes; solo la validación reconocida del servidor puede rechazarlos.
- Los chequeos cancelados no se vuelven a programar indefinidamente; las visitas cuyo
  resumen venció quedan fuera de la planificación de chequeos.
- Agenda muestra de lunes a domingo, identifica ambos meses/años si la semana cruza de
  período y cabe en pantallas pequeñas. Los enlaces reales de Recomendaciones usan esta
  misma agenda y conservan la fecha seleccionada.
- Encabezados y horas coherentes, acción «Programar visita», singular del resumen pendiente,
  guía para el resumen escrito y foco estable mientras se escribe.
- Tres fotos de Entrenar recuperadas y verificadas contra los originales de producción.
  El nivel básico distingue las técnicas no evaluadas y no muestra un total engañoso.
  Los resultados históricos conservan sus puntuaciones y reglas de aprobación.
- La limpieza de PAL protege identificadores compartidos con versiones vigentes o prácticas
  activas y conserva la referencia cuando falla el borrado remoto.
- Autenticación con reservas atómicas por teléfono/IP, Argon2 fuera del bucle asíncrono,
  límites de registro y comparación segura de invitaciones Unicode. No cambia la
  configuración que habilita el registro del piloto.
- Nginx resuelve las rutas de Entrenar, actualiza el destino de la API mediante DNS de
  Docker y limita las solicitudes a login/registro.
- Respaldos con dump atómico validado y envío cifrado opcional a restic, conservación ante
  errores y retención. Véase [instalación y recuperación](respaldos.md).

## Verificación

| Comprobación | Resultado |
| --- | --- |
| API completa con SQLite | 397 pruebas pasan, 1 omitida |
| API completa con PostgreSQL | 398 pruebas pasan |
| Web completa | 266 pruebas pasan |
| Revisión posterior del ajuste visual a 320 px | 25 pruebas focales pasan |
| TypeScript web y service worker; compilación Vite/PWA | Correctos |
| Ruff; mypy de los 70 archivos fuente de la API | Correctos |
| Migraciones: upgrade, coherencia de modelos y downgrade | Correctos en SQLite y PostgreSQL |
| Script de respaldo | Sintaxis shell correcta y 5 pruebas con dobles de Docker/restic |
| Nginx temporal oficial en Windows | Configuración válida; 403 reproducido antes y 200 después |
| Nginx: fotos, recursos ausentes, DNS y límite de acceso | Foto 200, recurso ausente 404, cambio DNS sin reinicio, 429 con Retry-After |

La revisión de navegador usó datos ficticios en una base independiente, llamadas apagadas,
Entrenar simulado y una sustitución de GPS exclusiva del servidor temporal de QA. No modifica
el control de ubicación de la compilación de producto. Se comprobaron Agenda a 320/390 px,
el encabezado de Recomendaciones, las cuatro fotos, el resumen guiado y el resultado básico.
Los servicios temporales se cerraron al terminar. La revisión independiente de seguridad
cerró sin hallazgos pendientes en este cambio.

## Aplicación operativa pendiente

Estas correcciones se entregan en Git; esta verificación no constituye un despliegue.

1. Desplegar el release revisado y aplicar Alembic hasta `0007` antes de iniciar la API
   actualizada. Si la base sigue en `0005`, también debe aplicarse `0006`. Respaldar antes
   y verificar salud, acceso, sincronización y trabajador después del despliegue.
2. Instalar las configuraciones de nginx y validar su sintaxis en el entorno Linux del
   servidor antes de recargar. La prueba local usó API y DNS simulados, sin tocar el VPS.
3. Elegir el destino externo, custodiar credenciales y contraseña de cifrado, realizar la
   primera copia y una restauración real; después activar el timer según el runbook.
   `UNO_BACKUP_OFFSITE=0` sigue siendo el valor inicial. No hay copia externa activada.
4. La corrección de limpieza de PAL está probada con proveedor simulado. No se ejecutó
   eliminación de recursos Tavus durante estas verificaciones.

Los otros hallazgos históricos de la auditoría de Claude y el módulo del nuevo boceto
continúan como contexto independiente; no se declaran resueltos por esta entrega.
