"""Remitentes de notificaciones: Web Push y correo.

Cada canal es una interfaz con varias implementaciones, para poder desarrollar y probar sin
servicios externos (mismo patrón que el ``ProveedorVoz`` del doc 02 T5.2):

- Push: ``WebPushSender`` (real, VAPID), ``LogPushSender`` (desarrollo),
  ``MemoryPushSender`` (pruebas).
- Correo: ``SmtpEmailSender`` (real), ``FileEmailSender`` (desarrollo: escribe ``.eml``),
  ``MemoryEmailSender`` (pruebas).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Protocol

from uno.config import Settings

log = logging.getLogger("uno.notifications")


# ------------------------------------------------------------------------------- push


@dataclass(frozen=True)
class PushTarget:
    endpoint: str
    p256dh: str
    auth: str


@dataclass(frozen=True)
class PushMessage:
    title: str
    body: str
    url: str = "/"
    tag: str | None = None
    kind: str = "generic"

    def to_json(self) -> str:
        return json.dumps(
            {
                "title": self.title,
                "body": self.body,
                "url": self.url,
                "tag": self.tag,
                "kind": self.kind,
            },
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class PushResult:
    ok: bool
    gone: bool = False  # la suscripción ya no existe (404 / 410): hay que desactivarla
    error: str | None = None


class PushSender(Protocol):
    async def send(self, target: PushTarget, message: PushMessage) -> PushResult: ...


class WebPushSender:
    """Envío real con el protocolo Web Push y llaves VAPID (RFC 8030 / RFC 8292)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.vapid_private_key or not settings.vapid_public_key:
            raise RuntimeError(
                "Faltan UNO_VAPID_PUBLIC_KEY / UNO_VAPID_PRIVATE_KEY (uno vapid-generate)"
            )
        self._private = settings.vapid_private_key
        self._subject = settings.vapid_subject

    async def send(self, target: PushTarget, message: PushMessage) -> PushResult:
        return await asyncio.to_thread(self._send_sync, target, message)

    def _send_sync(self, target: PushTarget, message: PushMessage) -> PushResult:
        from pywebpush import WebPushException, webpush

        try:
            webpush(
                subscription_info={
                    "endpoint": target.endpoint,
                    "keys": {"p256dh": target.p256dh, "auth": target.auth},
                },
                data=message.to_json(),
                vapid_private_key=self._private,
                vapid_claims={"sub": self._subject},
                ttl=3600,
                timeout=10,
            )
            return PushResult(ok=True)
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                return PushResult(ok=False, gone=True, error=f"http {status}")
            return PushResult(ok=False, error=f"webpush {status or 'error'}")
        except Exception as exc:  # red, DNS, llave inválida…
            return PushResult(ok=False, error=type(exc).__name__)


class LogPushSender:
    """Desarrollo: no envía nada, deja constancia en el registro."""

    async def send(self, target: PushTarget, message: PushMessage) -> PushResult:
        log.info("push (simulado) → %s… : %s", target.endpoint[:40], message.title)
        return PushResult(ok=True)


@dataclass
class MemoryPushSender:
    """Pruebas: guarda lo enviado y permite simular fallas por ``endpoint``."""

    sent: list[tuple[PushTarget, PushMessage]] = field(default_factory=list)
    gone_endpoints: set[str] = field(default_factory=set)
    failing_endpoints: set[str] = field(default_factory=set)

    async def send(self, target: PushTarget, message: PushMessage) -> PushResult:
        if target.endpoint in self.gone_endpoints:
            return PushResult(ok=False, gone=True, error="http 410")
        if target.endpoint in self.failing_endpoints:
            return PushResult(ok=False, error="simulado")
        self.sent.append((target, message))
        return PushResult(ok=True)


# ------------------------------------------------------------------------------- correo


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str | None = None


class EmailError(Exception):
    pass


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


def _to_mime(message: EmailMessage, sender: str) -> MimeMessage:
    mime = MimeMessage()
    mime["From"] = sender
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime["Date"] = formatdate(localtime=False)
    mime["Message-ID"] = make_msgid(domain="uno-visitas.local")
    mime.set_content(message.text)
    if message.html:
        mime.add_alternative(message.html, subtype="html")
    return mime


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    async def send(self, message: EmailMessage) -> None:
        import aiosmtplib

        s = self._s
        try:
            await aiosmtplib.send(
                _to_mime(message, s.email_from),
                hostname=s.smtp_host,
                port=s.smtp_port,
                username=s.smtp_user or None,
                password=s.smtp_password or None,
                start_tls=s.smtp_starttls,
                use_tls=s.smtp_ssl,
                timeout=15,
            )
        except Exception as exc:
            raise EmailError(type(exc).__name__) from exc


class FileEmailSender:
    """Desarrollo: escribe cada correo como archivo ``.eml`` en ``UNO_MAIL_DIR``."""

    def __init__(self, settings: Settings) -> None:
        self._dir = Path(settings.mail_dir)
        self._from = settings.email_from

    async def send(self, message: EmailMessage) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        path = self._dir / f"{stamp}.eml"
        await asyncio.to_thread(path.write_bytes, bytes(_to_mime(message, self._from)))
        log.info("correo (archivo) → %s", path.name)


@dataclass
class MemoryEmailSender:
    sent: list[EmailMessage] = field(default_factory=list)
    fail: bool = False

    async def send(self, message: EmailMessage) -> None:
        if self.fail:
            raise EmailError("simulado")
        self.sent.append(message)


# ------------------------------------------------------------------------------- fábricas


def build_push_sender(settings: Settings) -> PushSender:
    if settings.push_backend == "webpush":
        return WebPushSender(settings)
    if settings.push_backend == "memory":
        return MemoryPushSender()
    return LogPushSender()


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.email_backend == "smtp":
        return SmtpEmailSender(settings)
    if settings.email_backend == "memory":
        return MemoryEmailSender()
    return FileEmailSender(settings)
