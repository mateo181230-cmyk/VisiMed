"""Credenciales y tokens (doc 01 §10.8, §16; doc 02 T1.2).

- PIN de 6 dígitos con argon2id.
- Token de acceso: JWT de 24 h.
- Token de refresco: opaco, aleatorio, guardado solo como hash SHA-256.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from uno.config import Settings

PIN_RE = re.compile(r"^\d{6}$")
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")  # E.164


def normalize_phone(raw: str) -> str:
    """Quita espacios y guiones. El número se guarda en formato E.164 (``+573001234567``)."""
    cleaned = re.sub(r"[\s\-().]", "", raw or "")
    return cleaned


def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(phone))


def is_valid_pin(pin: str) -> bool:
    return bool(PIN_RE.match(pin))


def _hasher(settings: Settings) -> PasswordHasher:
    return PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
    )


def hash_pin(settings: Settings, pin: str) -> str:
    return _hasher(settings).hash(pin)


def verify_pin(settings: Settings, pin_hash: str, pin: str) -> bool:
    try:
        return _hasher(settings).verify(pin_hash, pin)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_verify(settings: Settings, pin: str) -> None:
    """Gasta el mismo tiempo que una verificación real (evita revelar si el celular existe)."""
    with contextlib.suppress(VerifyMismatchError, VerificationError, InvalidHashError):
        _hasher(settings).verify(_dummy_hash(settings), pin)


_DUMMY: dict[tuple[int, int, int], str] = {}


def _dummy_hash(settings: Settings) -> str:
    key = (settings.argon2_time_cost, settings.argon2_memory_cost, settings.argon2_parallelism)
    if key not in _DUMMY:
        _DUMMY[key] = _hasher(settings).hash("000000")
    return _DUMMY[key]


@dataclass(frozen=True)
class AccessToken:
    token: str
    expires_at: datetime


def create_access_token(
    settings: Settings, *, user_id: str, role: str, now: datetime
) -> AccessToken:
    exp = now + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "access",
    }
    return AccessToken(jwt.encode(payload, settings.jwt_secret, algorithm="HS256"), exp)


def decode_access_token(settings: Settings, token: str, *, now: datetime) -> dict[str, Any]:
    """Lanza ``jwt.PyJWTError`` si el token no es válido o venció.

    La vigencia se comprueba contra el reloj de la aplicación (``now``), no contra el del sistema,
    para que las pruebas puedan controlar el tiempo.
    """
    claims = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        options={
            "require": ["sub", "exp", "iat"],
            "verify_exp": False,
            "verify_iat": False,
        },
    )
    if claims.get("typ") != "access":
        raise jwt.InvalidTokenError("tipo de token inválido")
    ts = now.timestamp()
    if claims["exp"] <= ts:
        raise jwt.ExpiredSignatureError("el token venció")
    if claims["iat"] > ts + 60:  # tolerancia de 60 s por relojes desfasados
        raise jwt.InvalidTokenError("el token es del futuro")
    return claims


def new_refresh_token() -> tuple[str, str]:
    """Devuelve ``(token_en_claro, hash)``. Solo el hash se guarda."""
    raw = secrets.token_urlsafe(32)
    return raw, sha256_hex(raw)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
