"""Relaciona lo presentado con el catálogo sin copiar la línea de la agenda."""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from uno.modules.agenda.models import VisitLine
from uno.modules.catalog.models import Product, ProductLine


def _words(value: str) -> str:
    value = "".join(
        c for c in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(c) != "Mn"
    )
    return " ".join(re.findall(r"[a-z0-9]+", value))


async def refresh_discussed_lines(
    session: AsyncSession, visit_id: uuid.UUID, fields: dict[str, Any]
) -> None:
    entry = fields.get("products_discussed") or {}
    value = entry.get("value")
    await session.execute(
        delete(VisitLine).where(VisitLine.visit_id == visit_id, VisitLine.role == "discussed")
    )
    if not isinstance(value, str) or entry.get("confidence") == "low":
        return
    text = f" {_words(value)} "
    lines = (await session.scalars(select(ProductLine))).all()
    products = (await session.scalars(select(Product))).all()
    aliases: list[tuple[uuid.UUID, str]] = [
        (line.id, alias) for line in lines for alias in (line.code, line.name)
    ] + [(product.line_id, product.name) for product in products]
    matched = {
        line_id for line_id, alias in aliases if _words(alias) and f" {_words(alias)} " in text
    }
    for line_id in matched:
        session.add(
            VisitLine(
                visit_id=visit_id,
                line_id=line_id,
                role="discussed",
                source="rep_edit" if entry.get("source") == "rep_edit" else "extraction",
            )
        )
