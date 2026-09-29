# API v1: resumen

El contrato completo y tipado es el OpenAPI que genera el servidor (`python -m uno.export_openapi`); el frontend genera sus tipos de ahí (`pnpm gen:api`). Todos los errores tienen la forma `{ "detail": { "code": "…", "message": "…" } }`.

| Método | Ruta | Rol | Descripción |
| --- | --- | --- | --- |
| POST | `/v1/auth/login` | público | `{phone, pin}` → token de acceso (24 h) + cookie de refresco `httpOnly` (`Path=/v1/auth`, 30 días, rotatoria) |
| POST | `/v1/auth/refresh` · `/v1/auth/logout` | cookie | Rotación con detección de reutilización (revoca la familia; tolera 10 s de refrescos simultáneos) |
| GET | `/v1/me` | todos | Perfil |
| GET | `/v1/me/state?cursor=` | rep · admin | Bajada incremental de estado |
| POST | `/v1/sync` | rep · admin | Lote de eventos (≤ 100). Ver [sync-events.md](sync-events.md) |
| GET · PUT | `/v1/notifications/preferences` | autenticado | Ajustes de avisos |
| POST | `/v1/notifications/push/subscriptions` | autenticado | Registra el Web Push de este dispositivo. Solo endpoints HTTPS de servicios conocidos (FCM, Mozilla, Apple, Windows) |
| POST | `/v1/notifications/push/unsubscribe` | autenticado | Da de baja `{endpoint}` |
| POST | `/v1/notifications/email` | autenticado | Envía un código de 6 dígitos al correo (máx. 5 por hora) |
| POST | `/v1/notifications/email/verify` | autenticado | Confirma el código (máx. 5 intentos, vence en 15 min) |
| DELETE | `/v1/notifications/email` | autenticado | Quita el correo |
| POST | `/v1/notifications/test` | autenticado | Aviso de prueba (máx. 10 por hora) |
| GET · POST | `/v1/admin/users` | admin | Listar y crear usuarios (con correo pre-registrado y verificado) |
| PUT | `/v1/admin/users/{id}/notification-email` | admin | Registra de antemano el correo de avisos |
| GET | `/salud` | público | Estado sin datos personales |

**Excepción a «todo pasa por /v1/sync» (ADR-20):** los ajustes de avisos (suscripción push, verificación de correo) exigen conexión por naturaleza y usan rutas propias.

## Códigos de error frecuentes

`unauthorized` (401) · `forbidden` (403) · `too_many_attempts` (429, con `Retry-After`) · `phone_taken` (409) · `invalid_phone` · `invalid_pin` · `invalid_email` · `invalid_code` · `too_many_codes` · `too_many_tests` · `email_send_failed` (502) · `no_push_subscription` (409) · `email_not_verified` (409) · `invalid_endpoint` · `invalid_keys` · `invalid_reminder` · `invalid_time`.
