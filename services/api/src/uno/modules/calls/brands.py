"""Canonical brand names come from the active catalogue, never phonetic guesses."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from sqlalchemy import select

from uno.modules.catalog.models import Product, ProductLine
from .snc_report import SNCReport

PREFIX = "Marca pendiente de catálogo: "


def key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(c) != "Mn"))


async def catalogue(session, line_ids):
    rows = (await session.scalars(select(Product).join(ProductLine).where(
        Product.active.is_(True), ProductLine.active.is_(True), Product.line_id.in_(line_ids)
    ).order_by(Product.name))).all()
    return [{"id": str(p.id), "name": p.name} for p in rows]


def review(raw: str, entries: list[dict]):
    data = SNCReport.model_validate_json(raw)
    lookup = {key(p["name"]): p for p in entries}
    renamed, issues = {}, []
    for p in data.products:
        canonical = lookup.get(key(p.name))
        if canonical:
            renamed[p.name.casefold()] = canonical["name"]
            p.name = canonical["name"]
        else:
            candidates = sorted(entries, key=lambda x: SequenceMatcher(None, key(p.name), key(x["name"])).ratio(), reverse=True)
            issues.append({"name": p.name, "message": PREFIX + p.name,
                           "suggestions": [x["name"] for x in candidates[:3] if SequenceMatcher(None, key(p.name), key(x["name"])).ratio() >= .45]})
    for referral in data.referrals or []:
        if referral.products:
            referral.products = [renamed.get(n.casefold(), n) for n in referral.products]
    # Normalisation must not silently merge two products or change the order.
    data = SNCReport.model_validate_json(data.model_dump_json())
    return data.model_dump_json(), issues


async def review_report(session, visit, report):
    entries = await catalogue(session, [visit.primary_line_id])
    raw = (report.fields or {}).get("snc_report_json", {}).get("value")
    issues = []
    if raw:
        _, issues = review(raw, entries)
    report.problems = [p for p in report.problems or [] if not p.startswith(PREFIX)] + [x["message"] for x in issues]
    if issues:
        report.complete = False
    return entries, issues
