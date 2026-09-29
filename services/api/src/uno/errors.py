"""Errores de la API con código legible por máquina: ``{"detail": {"code", "message"}}``."""

from __future__ import annotations

from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail={"code": code, "message": message},
            headers=headers,
        )
        self.code = code


def unauthorized(message: str = "Debes ingresar de nuevo") -> ApiError:
    return ApiError(401, "unauthorized", message, {"WWW-Authenticate": "Bearer"})


def forbidden(message: str = "No tienes permiso para esto") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found(message: str = "No encontrado") -> ApiError:
    return ApiError(404, "not_found", message)
