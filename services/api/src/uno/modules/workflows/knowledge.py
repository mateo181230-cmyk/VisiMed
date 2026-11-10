"""Local PPTX extraction and approved, versioned retrieval. No web fallback."""

from __future__ import annotations

import hashlib
import io
import posixpath
import re
import shutil
import subprocess
import tempfile
import unicodedata
import uuid
import zipfile
from pathlib import Path

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import defer

from uno import clock
from uno.db import next_change_seq
from uno.errors import ApiError
from uno.modules.auth.permissions import line_ids, permits, require_capability
from uno.modules.catalog.models import ProductLine
from uno.modules.territory.schemas import Strict
from uno.modules.territory.service import audit

from .models import KnowledgeDocument

MAX_FILE = 20 * 1024 * 1024
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def xml(raw):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("XML no permitido")
    return ET.fromstring(raw)


def text_of(root):
    return "\n".join(
        "".join(t.text or "" for t in p.iter(A + "t")) for p in root.iter(A + "p")
    ).strip()


def ocr_image(raw, suffix):
    executable = shutil.which("tesseract")
    if not executable:
        return ""
    if suffix.lower() not in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        return ""
    with tempfile.TemporaryDirectory(prefix="uno-ocr-") as folder:
        source = Path(folder) / ("image" + suffix)
        source.write_bytes(raw)
        try:
            proc = subprocess.run(  # noqa: S603 - fixed executable; generated local file, no shell
                [executable, str(source), "stdout", "-l", "spa+eng"],
                capture_output=True,
                timeout=25,
                check=False,
            )
            return (
                proc.stdout.decode("utf-8", errors="replace")[:30000].strip()
                if proc.returncode == 0
                else ""
            )
        except subprocess.TimeoutExpired:
            return ""


def extract_slides(raw):
    if len(raw) > MAX_FILE:
        raise ValueError("El archivo supera 20 MB")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        entries = z.infolist()
        if len(entries) > 3000 or sum(i.file_size for i in entries) > 150 * 1024 * 1024:
            raise ValueError("Presentación demasiado grande para el piloto")
        if any(i.flag_bits & 1 for i in entries) or any(
            "vbaProject" in i.filename for i in entries
        ):
            raise ValueError("Usa una presentación PPTX sin macros ni cifrado")
        rels = {
            r.attrib["Id"]: r.attrib.get("Target", "")
            for r in xml(z.read("ppt/_rels/presentation.xml.rels"))
        }
        presentation = xml(z.read("ppt/presentation.xml"))
        ordered = [
            posixpath.normpath("ppt/" + rels[s.attrib[R + "id"]])
            for s in presentation.iter(P + "sldId")
        ]
        if not ordered or len(ordered) > 120:
            raise ValueError("Admite entre 1 y 120 diapositivas")
        slides = []
        for number, name in enumerate(ordered, 1):
            tree = xml(z.read(name))
            text = text_of(tree)
            method = "text"
            relfile = posixpath.dirname(name) + "/_rels/" + posixpath.basename(name) + ".rels"
            refs = list(xml(z.read(relfile))) if relfile in z.namelist() else []
            notes = ""
            for ref in refs:
                target = posixpath.normpath(
                    posixpath.dirname(name) + "/" + ref.attrib.get("Target", "")
                )
                if ref.attrib.get("TargetMode") == "External" or target not in z.namelist():
                    continue
                if ref.attrib.get("Type", "").endswith("/notesSlide"):
                    ntree = xml(z.read(target))
                    # Exclude slide-number placeholders from notes, retain real speaker notes.
                    note_parts = []
                    for shape in ntree.iter(P + "sp"):
                        ph = shape.find(".//" + P + "ph")
                        if ph is None or ph.attrib.get("type") != "sldNum":
                            note_parts.append(text_of(shape))
                    notes = "\n".join(t for t in note_parts if t)
            has_images = bool(list(tree.iter(P + "pic")))
            if len(text.strip()) < 50 and has_images:
                method = "ocr"
                snippets = []
                for ref in refs:
                    if (
                        not ref.attrib.get("Type", "").endswith("/image")
                        or ref.attrib.get("TargetMode") == "External"
                    ):
                        continue
                    target = posixpath.normpath(
                        posixpath.dirname(name) + "/" + ref.attrib.get("Target", "")
                    )
                    if target in z.namelist():
                        snippet = ocr_image(z.read(target), Path(target).suffix)
                        if snippet:
                            snippets.append(snippet)
                text = "\n".join([text, *snippets]).strip()
            slides.append(
                {
                    "number": number,
                    "text": text[:30000],
                    "notes": notes[:10000],
                    "method": method,
                    "has_images": has_images,
                    "needs_text": not bool(text.strip()),
                }
            )
        return slides


def check_line(actor, line):
    scope = line_ids(actor)
    if scope is not None and line not in scope:
        raise ApiError(403, "out_of_scope", "El material no pertenece a tu línea")


async def import_document(session, actor, filename, line_id, raw):
    require_capability(actor, "knowledge.manage")
    check_line(actor, line_id)
    if not await session.get(ProductLine, line_id):
        raise ApiError(422, "unknown_line", "Selecciona una línea válida")
    filename = filename.replace("\\", "/").split("/")[-1][:200]
    if not filename.lower().endswith(".pptx"):
        raise ApiError(422, "pptx_required", "Carga una presentación .pptx")
    sha = hashlib.sha256(raw).hexdigest()
    previous = await session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.sha256 == sha)
    )
    if previous:
        check_line(actor, previous.line_id)
        return previous
    import asyncio

    try:
        slides = await asyncio.to_thread(extract_slides, raw)
    except (ValueError, KeyError, zipfile.BadZipFile, ET.ParseError, DefusedXmlException):
        raise ApiError(
            422, "invalid_presentation", "No se pudo leer la presentación PPTX"
        ) from None
    # OCR never holds the global write lock used by live visit synchronisation.
    # Recheck after reserving it so simultaneous uploads stay idempotent.
    await next_change_seq(session)
    previous = await session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.sha256 == sha)
    )
    if previous:
        check_line(actor, previous.line_id)
        return previous
    title = filename[:-5]
    version = (
        await session.scalar(
            select(func.max(KnowledgeDocument.version)).where(
                KnowledgeDocument.line_id == line_id, KnowledgeDocument.title == title
            )
        )
        or 0
    ) + 1
    row = KnowledgeDocument(
        line_id=line_id,
        filename=filename,
        title=title,
        sha256=sha,
        version=version,
        slides=slides,
        original=raw,
        created_at=clock.now(),
    )
    session.add(row)
    await session.flush()
    await audit(session, actor, "knowledge_imported", row.id, row.version)
    return row


def document_json(row, detail=False):
    data = {
        "id": str(row.id),
        "line_id": str(row.line_id),
        "title": row.title,
        "filename": row.filename,
        "sha256": row.sha256,
        "version": row.version,
        "revision": row.revision,
        "status": row.status,
        "slide_count": len(row.slides),
        "ocr_count": sum(s["method"] == "ocr" for s in row.slides),
        "needs_text": sum(s["needs_text"] for s in row.slides),
        "review_note": row.review_note,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "reviewed_by": str(row.reviewed_by) if row.reviewed_by else None,
    }
    if detail:
        data["slides"] = row.slides
    return data


async def get_document(session, actor, id):
    row = await session.scalar(
        select(KnowledgeDocument)
        .options(defer(KnowledgeDocument.original))
        .where(KnowledgeDocument.id == id)
    )
    if not row:
        raise ApiError(404, "missing_document", "No encontramos el material")
    check_line(actor, row.line_id)
    if row.status != "approved" and not permits(actor, "knowledge.manage"):
        raise ApiError(403, "not_approved", "Este material todavía no está aprobado")
    return row


class Review(Strict):
    id: uuid.UUID
    status: str = Field(pattern="^(approved|withdrawn|draft)$")
    note: str = Field(min_length=8, max_length=2000)
    reviewed_visuals: bool = False


class SlideEdit(Strict):
    id: uuid.UUID
    number: int = Field(ge=1, le=120)
    text: str = Field(min_length=1, max_length=30000)


async def review_command(session, actor, command):
    require_capability(actor, "knowledge.manage")
    p = (SlideEdit if command.type == "knowledge.slide" else Review).model_validate(command.payload)
    row = await get_document(session, actor, p.id)
    if row.revision != command.expected_version:
        raise ApiError(
            409, "document_changed", "Otra persona cambió el material. Actualiza la biblioteca"
        )
    if command.type == "knowledge.slide":
        if row.status != "draft":
            raise ApiError(
                409, "approved_immutable", "Devuelve el material a borrador antes de corregirlo"
            )
        if p.number > len(row.slides):
            raise ApiError(422, "missing_slide", "Diapositiva inexistente")
        slides = [dict(s) for s in row.slides]
        slides[p.number - 1].update(text=p.text.strip(), method="reviewed", needs_text=False)
        row.slides = slides
    elif command.type == "knowledge.review":
        if p.status == "approved" and (
            not p.reviewed_visuals or any(s["needs_text"] for s in row.slides)
        ):
            raise ApiError(
                422,
                "review_required",
                "Revisa el original, las figuras y el OCR; completa las diapositivas sin texto",
            )
        if p.status == "approved":
            # One active approved version per title/line. Keep superseded versions auditable.
            older = (
                await session.scalars(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.title == row.title,
                        KnowledgeDocument.line_id == row.line_id,
                        KnowledgeDocument.id != row.id,
                        KnowledgeDocument.status == "approved",
                    )
                )
            ).all()
            for old in older:
                old.status = "withdrawn"
                old.revision += 1
        row.status, row.review_note = p.status, p.note.strip()
        row.reviewed_by, row.reviewed_at = actor.id, clock.now()
    else:
        raise ApiError(422, "unknown_command", "Operación de biblioteca desconocida")
    row.revision += 1
    await audit(session, actor, "knowledge_reviewed", row.id, row.revision)
    return document_json(row)


def tokens(value):
    value = "".join(
        c for c in unicodedata.normalize("NFD", value.casefold()) if unicodedata.category(c) != "Mn"
    )
    stop = {
        "que",
        "para",
        "con",
        "una",
        "como",
        "del",
        "los",
        "las",
        "por",
        "son",
        "este",
        "esta",
        "tiene",
        "cual",
        "sobre",
        "puede",
    }
    return {t for t in re.findall(r"[a-z0-9]+", value) if len(t) >= 3 and t not in stop}


async def retrieve(session, actor, question, line_id=None):
    query = (
        select(KnowledgeDocument)
        .options(defer(KnowledgeDocument.original))
        .where(KnowledgeDocument.status == "approved")
    )
    scope = line_ids(actor)
    if scope is not None:
        query = query.where(KnowledgeDocument.line_id.in_(scope))
    if line_id:
        query = query.where(KnowledgeDocument.line_id == line_id)
    terms = tokens(question)
    hits = []
    for doc in (await session.scalars(query)).all():
        for slide in doc.slides:
            body = slide["text"] + "\n" + slide.get("notes", "")
            overlap = terms & tokens(body + " " + doc.title)
            if not overlap:
                continue
            # Preserve source order and adjacent qualifiers; do not assemble a
            # synthetic clinical statement by sorting disconnected sentences.
            paragraphs = body.splitlines()
            best = max(range(len(paragraphs)), key=lambda i: len(tokens(paragraphs[i]) & terms))
            excerpt = "\n".join(paragraphs[max(0, best - 2):best + 5])[:1800]
            hits.append(
                {
                    "score": len(overlap) / max(1, len(terms)),
                    "document_id": str(doc.id),
                    "title": doc.title,
                    "version": doc.version,
                    "revision": doc.revision,
                    "slide": slide["number"],
                    "excerpt": excerpt,
                    "method": slide["method"],
                    "href": (
                        f"/territorio/?module=library&document={doc.id}&slide={slide['number']}"
                    ),
                }
            )
    hits.sort(key=lambda h: (-h["score"], h["title"], h["slide"]))
    return hits[:5]
