"""Configuración de la API. Todo viene del entorno (prefijo ``UNO_``) o de un archivo ``.env``.

Los secretos nunca viven en el repositorio: ``.env`` está en ``.gitignore`` y ``.env.example``
solo documenta las variables (doc 01 §16).
"""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-change-me-dev-only-change-me"  # noqa: S105  (solo desarrollo)

# Secretos de terceros (llaves de ElevenLabs…) fuera del repositorio y de la carpeta que sincroniza
# OneDrive: ``~/.uno-visitas/secrets.env``. Si no existe, se ignora. Las variables de entorno y el
# ``.env`` local tienen menos prioridad que este archivo solo cuando ambos definen la misma clave.
SECRETS_FILE = Path.home() / ".uno-visitas" / "secrets.env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", str(SECRETS_FILE)), env_prefix="UNO_", extra="ignore"
    )

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "sqlite+aiosqlite:///./var/uno-dev.db"

    # --- autenticación (doc 01 §10.8, §16) ---
    jwt_secret: str = DEV_JWT_SECRET
    access_token_minutes: int = 24 * 60
    refresh_token_days: int = 30
    cookie_secure: bool = False
    refresh_cookie_name: str = "uno_refresh"
    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 4
    login_max_failures: int = 5
    login_window_minutes: int = 15
    pilot_invite_code: str = ""  # registro de visitadores cerrado salvo piloto con código

    # --- zona horaria del negocio ---
    default_timezone: str = "America/Bogota"

    # --- HTTP ---
    cors_origins: list[str] = []
    app_base_url: str = "http://localhost:5173"

    # --- notificaciones ---
    push_backend: Literal["webpush", "log", "memory"] = "log"
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:soporte@localhost"
    # Solo se aceptan suscripciones hacia servicios de push conocidos (evita SSRF)
    push_allowed_hosts: list[str] = [
        "fcm.googleapis.com",
        "updates.push.services.mozilla.com",
        "web.push.apple.com",
        "push.apple.com",
        "notify.windows.com",
    ]

    email_backend: Literal["file", "smtp", "memory"] = "file"
    email_from: str = "UNO Visitas <no-reply@localhost>"
    mail_dir: str = "./var/mail"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    smtp_ssl: bool = False

    notify_include_names: bool = True  # nombres de médicos en avisos (ver Q15 del doc 01)
    reminder_poll_seconds: int = 60
    embedded_worker: bool = False  # ejecuta el trabajador dentro del proceso (solo desarrollo)

    # --- llamadas de resumen (doc 01 §12: ElevenLabs sobre una troncal SIP de Telyaco) ---
    # ``off``: nunca se llama a nadie (valor seguro por defecto). ``fake``: proveedor simulado.
    call_backend: Literal["off", "fake", "elevenlabs"] = "off"
    elevenlabs_api_key: str = ""
    elevenlabs_base_url: str = "https://api.elevenlabs.io"
    elevenlabs_agent_id: str = ""
    elevenlabs_phone_number_id: str = ""  # número desde el que sale la llamada (Twilio o SIP)
    # ``auto``: se detecta mirando el número. Solo hace falta fijarlo para evitar esa consulta.
    elevenlabs_phone_channel: Literal["auto", "sip_trunk", "twilio"] = "auto"
    elevenlabs_webhook_secret: str = ""  # secreto HMAC del webhook de fin de llamada
    # Fuera de producción solo se llama a estos celulares (lista separada por comas, E.164).
    call_allowed_phones: str = ""
    # Identifica la visita por su médico. Puede desactivarse para usar hora e institución.
    call_include_doctor_names: bool = True
    # SOLO DESARROLLO: todas las llamadas salen a este celular en vez de al del visitador.
    # Sirve para probar con la cuenta de demostración y que suene el teléfono de quien prueba.
    # Prohibido en producción.
    call_phone_override: str = ""
    call_window_start_hour: int = 7  # no se llama antes de esta hora local…
    call_window_end_hour: int = 19  # …ni desde esta
    call_closing_hour: int = 18  # a esta hora se llama con lo que haya quedado pendiente
    call_batch_wait_seconds: int = 20  # espera tras un «Terminé» por si sigue «Otro médico aquí»
    call_max_visits_per_call: int = Field(default=1, ge=1, le=5)  # piloto: una ficha por llamada
    call_retry_minutes: str = "5,15"  # reintentos si no contesta (PRD C1)
    call_poll_seconds: int = 5
    call_result_timeout_minutes: int = 15  # incluye la llamada y el análisis del proveedor
    call_busy_visit_hours: int = 3  # una visita en curso más de estas horas no bloquea la llamada
    call_giveup_hours: int = 24  # sin entrevista pasado este plazo → «sin entrevista»

    # --- Entrenar: práctica con médico virtual (doc 04; Tavus con voz de ElevenLabs) ---
    # ``off``: el médico no está disponible (valor seguro). ``fake``: visita simulada (desarrollo).
    training_backend: Literal["off", "fake", "tavus"] = "off"
    tavus_api_key: str = ""
    tavus_base_url: str = "https://tavusapi.com"
    # URL pública HTTPS de esta API para que Tavus avise el fin de la visita. Sin ella, la
    # transcripción se consulta cada pocos segundos (funciona igual, un poco más lento).
    tavus_callback_base_url: str = ""
    # Llave de ElevenLabs que se entrega a Tavus solo si la voz del médico es privada (un clon).
    # Las voces públicas de la biblioteca no la necesitan.
    training_tts_api_key: str = ""
    training_max_call_seconds: int = 300  # el Anexo fija 5 minutos por visita
    training_attempts_per_day: int = 6  # control de costo por visitador
    training_poll_seconds: int = 5
    training_transcript_timeout_minutes: int = 5  # sin transcripción tras esto: «sin conversación»

    @model_validator(mode="after")
    def _check_production(self) -> Settings:
        if self.env == "prod":
            if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("UNO_JWT_SECRET debe definirse (≥ 32 caracteres) en producción")
            if not self.cookie_secure:
                raise ValueError("UNO_COOKIE_SECURE debe ser true en producción")
        if self.env == "prod" and self.call_phone_override:
            raise ValueError("UNO_CALL_PHONE_OVERRIDE no puede usarse en producción")
        if self.call_backend == "elevenlabs" and not (
            self.elevenlabs_api_key and self.elevenlabs_agent_id and self.elevenlabs_phone_number_id
        ):
            raise ValueError(
                "call_backend=elevenlabs exige UNO_ELEVENLABS_API_KEY, UNO_ELEVENLABS_AGENT_ID y "
                "UNO_ELEVENLABS_PHONE_NUMBER_ID"
            )
        if self.training_backend == "tavus" and not self.tavus_api_key:
            raise ValueError("training_backend=tavus exige UNO_TAVUS_API_KEY")
        return self

    def dial_phone(self, representative_phone: str) -> str:
        """A qué celular se llama: el del visitador, o el de prueba si hay desvío (desarrollo)."""
        return self.call_phone_override or representative_phone

    @property
    def allowed_call_phones(self) -> frozenset[str]:
        return frozenset(p.strip() for p in self.call_allowed_phones.split(",") if p.strip())

    @property
    def call_retry_delays(self) -> list[timedelta]:
        return [timedelta(minutes=int(m)) for m in self.call_retry_minutes.split(",") if m.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
