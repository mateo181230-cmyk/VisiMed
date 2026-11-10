"""Auditable commercial imports. Market cuts never become field visits or live stock."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from uno import clock
from uno.errors import ApiError
from uno.modules.auth.permissions import line_ids, require_capability
from uno.modules.calls.brands import catalogue, key
from .models import CommercialBatch


def allowed(actor):
    require_capability(actor, "dashboard.read")
    if actor.management_profile != "line":
        raise ApiError(403, "line_only", "La importación comercial corresponde a gerencia de línea")


def parse_csv(raw, source):
    if len(raw) > 20 * 1024 * 1024:
        raise ApiError(413, "too_large", "Usa un CSV de hasta 20 MB, filtrado por Bogotá y SNC")
    if source not in ("distribution", "chains", "closeup"):
        raise ApiError(422, "source", "Selecciona distribución, cadenas o Close-Up")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        required = {"period", "product", "entity", "metric", "unit", "value", "source_row", "sheet", "source_file", "source_sha256", "city"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Columnas requeridas: " + ", ".join(sorted(required)))
        rows, errors, seen = [], [], {}
        for index, item in enumerate(reader, 2):
            if index > 30001:
                raise ValueError("Máximo 30.000 filas por carga")
            try:
                if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", item["period"]):
                    raise ValueError("Período inválido; usa AAAA-MM")
                if key(item["city"]) not in ("bogota", "bogotadc", "santafedebogota", "bogotadistritocapital"):
                    raise ValueError("El piloto admite datos de Bogotá")
                if item["metric"] not in ("inventory", "rotation", "distribution", "sales", "mov") or item["unit"] not in ("units", "COP", "source_mov"):
                    raise ValueError("Métrica o unidad desconocida")
                if not re.fullmatch(r"[a-f0-9]{64}", item["source_sha256"]) or int(item["source_row"]) < 1:
                    raise ValueError("Falta trazabilidad del archivo y fila originales")
                if not item["product"].strip() or not item["entity"].strip():
                    raise ValueError("Falta producto o entidad")
                value = None if item["value"].strip() == "" else Decimal(item["value"])
                if value is not None and not value.is_finite():
                    raise ValueError("Valor no finito")
                identity = [source, item["period"], key(item["product"]), key(item["entity"]), item["metric"], item["unit"], item.get("dimensions", "")]
                rowkey = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
                if rowkey in seen:
                    raise ValueError("Fila comercial duplicada; concilia la dimensión antes de cargar")
                seen[rowkey] = True
                rows.append({**{k: str(v or "")[:600] for k, v in item.items()}, "value": str(value) if value is not None else None, "key": rowkey})
            except (ValueError, InvalidOperation, TypeError) as error:
                errors.append({"row": index, "message": str(error)})
        if not rows and not errors:
            raise ValueError("El archivo no tiene filas")
        return rows, errors
    except (UnicodeError, csv.Error, ValueError) as error:
        raise ApiError(422, "invalid_csv", str(error)) from None


def render(batch, detail=False):
    rows = batch.data["rows"]
    out = {"id": str(batch.id), "filename": batch.filename, "source": batch.source, "status": batch.status, "version": batch.version,
           "created_at": batch.created_at.isoformat(), "periods": sorted({r["period"] for r in rows}), "rows": len(rows),
           "missing_values": sum(r["value"] is None for r in rows), "matched_brand_rows": sum(bool(r.get("product_id")) for r in rows),
           "unmatched_brand_rows": sum(not r.get("product_id") for r in rows), "errors": batch.data["errors"][:100],
           "error_count": len(batch.data["errors"]), "sha256": batch.sha256}
    if detail:
        out["preview"] = rows[:100]
    return out


async def preview(session, actor, filename, source, raw):
    allowed(actor)
    lines = line_ids(actor)
    if not lines:
        raise ApiError(403, "line_scope", "Falta el alcance de línea")
    digest = hashlib.sha256(source.encode() + str(lines[0]).encode() + raw).hexdigest()
    existing = await session.scalar(select(CommercialBatch).where(CommercialBatch.sha256 == digest))
    if existing:
        return render(existing, True)
    rows, errors = parse_csv(raw, source)
    from uno.db import next_change_seq
    await next_change_seq(session)
    existing = await session.scalar(select(CommercialBatch).where(CommercialBatch.sha256 == digest))
    if existing:
        return render(existing, True)
    entries = await catalogue(session, lines)
    for row in rows:
        matches = [x for x in entries if re.match(r"^" + re.escape(x["name"]) + r"(?:\b|\s|$)", row["product"], re.I)]
        row["product_id"] = matches[0]["id"] if len(matches) == 1 else None
        row["brand"] = matches[0]["name"] if len(matches) == 1 else row["product"]
    batch = CommercialBatch(line_id=lines[0], filename=filename.replace("\\", "/").split("/")[-1][:200], source=source,
                            sha256=digest, data={"rows": rows, "errors": errors}, created_by=actor.id, created_at=clock.now())
    session.add(batch); await session.flush()
    return render(batch, True)


async def confirm(session, actor, command):
    allowed(actor)
    try:
        id = uuid.UUID(command.payload["id"])
    except (KeyError, ValueError):
        raise ApiError(422, "id", "Carga comercial inválida") from None
    batch = await session.get(CommercialBatch, id)
    if not batch or batch.line_id not in line_ids(actor):
        raise ApiError(404, "not_found", "No encontramos la carga")
    if batch.status == "committed":
        return render(batch)
    if batch.version != command.expected_version:
        raise ApiError(409, "changed", "La carga cambió. Actualiza la vista.")
    if batch.data["errors"]:
        raise ApiError(422, "needs_reconciliation", "Corrige todas las filas rechazadas antes de confirmar")
    previous = (await session.scalars(select(CommercialBatch).where(CommercialBatch.status == "committed", CommercialBatch.line_id == batch.line_id))).all()
    existing = {r["key"] for old in previous for r in old.data["rows"]}
    if any(r["key"] in existing for r in batch.data["rows"]):
        raise ApiError(409, "duplicate_cut", "Este corte contiene registros ya importados. No se sumará dos veces.")
    batch.status = "committed"; batch.version += 1; batch.committed_at = clock.now()
    return render(batch)


async def list_batches(session, actor):
    allowed(actor)
    return (await session.scalars(select(CommercialBatch).where(CommercialBatch.line_id.in_(line_ids(actor))).order_by(CommercialBatch.created_at.desc()))).all()


async def summary(session, actor):
    batches = await list_batches(session, actor)
    buckets = defaultdict(lambda: {"sum": Decimal(0), "observed": 0, "missing": 0, "entities": set(), "brand_matched": 0})
    for batch in batches:
        if batch.status != "committed":
            continue
        for row in batch.data["rows"]:
            k = (batch.source, row["period"], row["brand"], row["metric"], row["unit"])
            b = buckets[k]; b["entities"].add(row["entity"])
            if row["value"] is None:
                b["missing"] += 1
            else:
                b["sum"] += Decimal(row["value"]); b["observed"] += 1
            b["brand_matched"] += bool(row.get("product_id"))
    rows = [{"source": k[0], "period": k[1], "brand": k[2], "metric": k[3], "unit": k[4],
             "value": str(b["sum"]) if b["observed"] else None, "observed": b["observed"], "missing": b["missing"], "entities": len(b["entities"]), "matched": b["brand_matched"]}
            for k, b in sorted(buckets.items())]
    return {"batches": [render(b) for b in batches], "series": rows,
            "note": "Cortes comerciales de Bogotá. No son inventario en tiempo real ni prueban ventas causadas por visitas. MOV conserva la unidad original no validada; no se suma con unidades o COP."}
