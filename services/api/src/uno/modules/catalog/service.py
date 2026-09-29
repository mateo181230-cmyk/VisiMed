"""Operaciones de catálogo usadas por la línea de comandos (no expuestas por la API)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uno.db import next_change_seq
from uno.modules.catalog.models import Institution


class InstitutionLookupError(Exception):
    """No se pudo identificar una única institución; el mensaje se muestra tal cual."""


async def find_institution(
    session: AsyncSession, *, name: str | None = None, institution_id: uuid.UUID | None = None
) -> Institution:
    """Busca por id, o por nombre exacto (sin distinguir mayúsculas). Debe haber exactamente una."""
    if (name is None) == (institution_id is None):
        raise InstitutionLookupError("Indica la institución con --name o con --id (uno solo)")
    if institution_id is not None:
        found = await session.get(Institution, institution_id)
        if found is None:
            raise InstitutionLookupError("No existe una institución con ese id")
        return found
    wanted = (name or "").strip().lower()
    rows = (
        (await session.execute(select(Institution).where(func.lower(Institution.name) == wanted)))
        .scalars()
        .all()
    )
    if not rows:
        raise InstitutionLookupError(f"No existe una institución llamada «{name}»")
    if len(rows) > 1:
        ids = ", ".join(str(r.id) for r in rows)
        raise InstitutionLookupError(f"Hay {len(rows)} con ese nombre; usa --id ({ids})")
    return rows[0]


async def set_institution_reference(
    session: AsyncSession,
    institution: Institution,
    *,
    lat: float,
    lng: float,
    radius_m: int | None = None,
) -> Institution:
    """Fija el punto de referencia (y opcionalmente el radio) de una institución.

    La referencia queda marcada como ``manual`` y sube ``change_seq`` para que el teléfono la
    baje en su próxima sincronización. No recalcula visitas ya marcadas: su estado de geocerca
    se calculó con la referencia vigente en ese momento.
    """
    institution.lat = lat
    institution.lng = lng
    institution.ref_source = "manual"
    if radius_m is not None:
        institution.radius_m = radius_m
    institution.change_seq = await next_change_seq(session)
    await session.commit()
    return institution
