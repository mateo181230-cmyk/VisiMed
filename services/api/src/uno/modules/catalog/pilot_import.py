"""Idempotent, create-only import of the supplied SNC commercial catalogue."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from uno.db import next_change_seq
from uno.errors import ApiError

from .models import CommercialCycle, Product, ProductLine, ProductPresentation

NAMESPACE = uuid.UUID("7cc39d61-14ba-44ca-9cb0-13e070424e32")


async def import_catalog(session, payload: dict) -> dict:
    line = await session.scalar(select(ProductLine).where(ProductLine.code == "SNC"))
    if not line:
        raise ApiError(422, "missing_line", "Primero configura la línea SNC")
    seq = await next_change_seq(session)
    products = {
        x.name.upper(): x
        for x in (await session.scalars(select(Product).where(Product.line_id == line.id))).all()
    }
    counts = {"brands_created": 0, "presentations_created": 0, "cycles_created": 0}
    seen = set()
    for item in payload["presentations"]:
        barcode, brand = item.get("barcode"), item["brand"].strip().upper()
        source = dict(item["source"])
        if barcode is None:
            # A launch can be approved before its commercial barcode is supplied.
            # Keep that field unknown; an explicit source reference supplies identity.
            reference = item.get("reference", "").strip()
            if not reference or len(reference) > 160 or not source.get("file") or len(source.get("sha256", "")) != 64:
                raise ApiError(422, "invalid_catalog", "La presentación sin código requiere referencia y fuente verificable")
            identity = "source:" + reference
            source["catalog_reference"] = reference
            source["barcode_status"] = "not_supplied"
        elif isinstance(barcode, str) and barcode.isdigit() and len(barcode) in (8, 12, 13, 14):
            identity = barcode
        else:
            raise ApiError(422, "invalid_catalog", "Revisa códigos duplicados o inválidos")
        if identity in seen:
            raise ApiError(422, "invalid_catalog", "Revisa códigos duplicados o inválidos")
        seen.add(identity)
        presentation_id = uuid.uuid5(NAMESPACE, identity)
        existing = (
            await session.get(ProductPresentation, presentation_id) if barcode is None
            else await session.scalar(select(ProductPresentation).where(ProductPresentation.barcode == barcode))
        )
        if existing:
            if (
                existing.name != item["name"]
                or brand not in products
                or existing.product_id != products[brand].id
                or existing.pack_units != item.get("pack_units")
                or existing.sale_class != item.get("sale_class")
            ):
                raise ApiError(
                    409,
                    "catalog_conflict",
                    "La presentación ya existe con otros datos; requiere conciliación",
                )
            continue
        product = products.get(brand)
        if not product:
            product = Product(
                id=uuid.uuid5(NAMESPACE, "SNC:" + brand),
                line_id=line.id,
                name=brand,
                active=True,
                change_seq=seq,
            )
            session.add(product)
            await session.flush()
            products[brand] = product
            counts["brands_created"] += 1
        session.add(
            ProductPresentation(
                id=presentation_id,
                product_id=product.id,
                barcode=barcode,
                name=item["name"],
                pack_units=item.get("pack_units"),
                sale_class=item.get("sale_class"),
                source=source,
                active=True,
                change_seq=seq,
            )
        )
        counts["presentations_created"] += 1
    for item in payload["cycles"]:
        starts, ends = date.fromisoformat(item["starts_on"]), date.fromisoformat(item["ends_on"])
        if starts > ends or not 1 <= item["working_days"] <= 31:
            raise ApiError(422, "invalid_cycle", "Fechas o días del ciclo inválidos")
        existing = await session.scalar(
            select(CommercialCycle).where(CommercialCycle.code == item["code"])
        )
        if existing:
            if existing.line_id != line.id or (
                existing.starts_on,
                existing.ends_on,
                existing.working_days,
            ) != (
                starts,
                ends,
                item["working_days"],
            ):
                raise ApiError(409, "cycle_conflict", "El ciclo existente requiere conciliación")
            continue
        session.add(
            CommercialCycle(
                id=uuid.uuid5(NAMESPACE, item["code"]),
                code=item["code"],
                line_id=line.id,
                starts_on=starts,
                ends_on=ends,
                working_days=item["working_days"],
                source=item["source"],
                active=True,
            )
        )
        counts["cycles_created"] += 1
    await session.flush()
    return counts
