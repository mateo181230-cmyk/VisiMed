"""Textos de las notificaciones (español de Colombia). Sin datos de pacientes ni identificadores."""

from __future__ import annotations

from datetime import datetime
from html import escape

from uno.modules.notifications.senders import EmailMessage


def format_time(local: datetime) -> str:
    """``10:30 AM`` (formato de la app)."""
    hour = local.hour % 12 or 12
    suffix = "AM" if local.hour < 12 else "PM"
    return f"{hour}:{local.minute:02d} {suffix}"


_DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MONTHS = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def format_date(local: datetime) -> str:
    return f"{_DAYS[local.weekday()]} {local.day} de {_MONTHS[local.month - 1]}"


def _who(doctor_name: str | None, institution: str | None, include_names: bool) -> str:
    if include_names and doctor_name:
        return f"{doctor_name} · {institution}" if institution else doctor_name
    return institution or "tu próxima visita"


def visit_reminder(
    *,
    local_time: datetime,
    minutes_before: int,
    doctor_name: str | None,
    institution: str | None,
    include_names: bool,
) -> tuple[str, str]:
    """Título y cuerpo de un recordatorio de visita."""
    hora = format_time(local_time)
    title = f"Visita en {minutes_before} min" if minutes_before else f"Visita a las {hora}"
    return title, f"{hora} · {_who(doctor_name, institution, include_names)}"


def daily_digest(
    *,
    local_day: datetime,
    count: int,
    first_time: datetime,
    first_doctor: str | None,
    first_institution: str | None,
    include_names: bool,
) -> tuple[str, str]:
    plural = "visita" if count == 1 else "visitas"
    title = f"Tu agenda de hoy: {count} {plural}"
    who = _who(first_doctor, first_institution, include_names)
    return title, f"Empiezas a las {format_time(first_time)} · {who}"


def to_email(to: str, title: str, body: str, app_url: str) -> EmailMessage:
    text = f"{title}\n\n{body}\n\nAbrir UNO Visitas: {app_url}\n"
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:auto">'
        f'<h2 style="margin:0 0 8px">{escape(title)}</h2>'
        f'<p style="font-size:16px;color:#333;margin:0 0 16px">{escape(body)}</p>'
        f'<p><a href="{escape(app_url)}" style="background:#1d6cf0;color:#fff;padding:12px 20px;'
        'border-radius:10px;text-decoration:none;display:inline-block">Abrir UNO Visitas</a></p>'
        "</div>"
    )
    return EmailMessage(to=to, subject=title, text=text, html=html)


def verification_email(to: str, code: str, minutes: int) -> EmailMessage:
    subject = "Tu código de UNO Visitas"
    text = (
        f"Tu código de verificación es {code}.\n"
        f"Vence en {minutes} minutos. Si no lo pediste, ignora este mensaje.\n"
    )
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:auto">'
        "<p>Tu código de verificación es</p>"
        '<p style="font-size:32px;font-weight:700;letter-spacing:6px;margin:8px 0">'
        f"{escape(code)}</p>"
        f'<p style="color:#666">Vence en {minutes} minutos. '
        "Si no lo pediste, ignora este mensaje.</p>"
        "</div>"
    )
    return EmailMessage(to=to, subject=subject, text=text, html=html)
