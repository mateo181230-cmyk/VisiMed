"""Publicación de los médicos virtuales en Tavus (doc 04 §5.7; ``uno training-apply``).

Un PAL por versión de escenario. Publicar solo crea un PAL nuevo si cambió la huella del contenido;
la versión anterior queda retirada (sus PAL se borran con ``training-cleanup`` cuando ya no hay
prácticas vivas que los usen). La cuenta de Tavus es compartida: nunca se toca un PAL cuyo nombre no
empiece por ``PAL_PREFIX``.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, or_, select

from uno import clock
from uno.config import Settings
from uno.context import AppContext
from uno.modules.training import prompts
from uno.modules.training.content import Catalog, Scenario, get_catalog
from uno.modules.training.models import ACTIVE_STATUSES, PracticeAttempt, TrainingScenarioVersion
from uno.modules.training.provider import PAL_PREFIX, ProviderError, TavusProvider


def pal_name(scenario: Scenario, version: int, digest: str) -> str:
    """El nombre lleva la huella del contenido: publicar dos veces lo mismo reutiliza el PAL."""
    return f"{PAL_PREFIX} · {scenario.product} · {scenario.doctor.name} · v{version} · {digest[:8]}"


def _plain(text: str) -> str:
    """Tavus limpia los nombres (quita puntos, guiones, paréntesis): se compara sin signos."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_text.lower())


def _reusable(pals: list[dict[str, Any]], scenario: Scenario, digest: str) -> str | None:
    """PAL ya publicado en Tavus con este mismo contenido (otra base de datos, otro intento)."""
    doctor = _plain(scenario.doctor.name)
    for pal in pals:
        name = str(pal.get("pal_name") or "")
        plain = _plain(name)
        if name.startswith(PAL_PREFIX) and doctor in plain and plain.endswith(digest[:8]):
            return str(pal.get("pal_id") or "") or None
    return None


def build_pal(
    catalog: Catalog, scenario: Scenario, settings: Settings, version: int
) -> dict[str, Any]:
    """Cuerpo de ``POST /v2/pals``: prompt compilado, cara, voz de ElevenLabs y turnos."""
    tavus = catalog.common.tavus
    tts: dict[str, Any] = {
        "tts_engine": "elevenlabs",
        "external_voice_id": scenario.casting.voice_id,
        "tts_model_name": scenario.casting.tts_model,
        "voice_settings": tavus["voice_settings"],
    }
    if settings.training_tts_api_key:
        tts["api_key"] = settings.training_tts_api_key
    return {
        "pal_name": pal_name(scenario, version, catalog.content_hash(scenario)),
        "pipeline_mode": "full",
        "default_face_id": scenario.casting.face_id,
        "languages": ["es"],
        "system_prompt": prompts.system_prompt(scenario, catalog.common),
        "context": prompts.scenario_context(scenario, catalog.common),
        "disclosure_type": "off",
        "layers": {
            "llm": {"model": tavus["llm_model"], "speculative_inference": True},
            "tts": tts,
            "stt": {"stt_engine": "tavus-auto", "hotwords": tavus["stt_hotwords"]},
            "perception": {"perception_model": "off"},
            "conversational_flow": {
                "turn_detection_model": tavus["turn_detection_model"],
                "turn_taking_patience": scenario.flow.turn_taking_patience,
                "pal_interruptibility": scenario.flow.pal_interruptibility,
                "idle_engagement": scenario.flow.idle_engagement,
            },
        },
    }


async def apply(
    ctx: AppContext, *, dry_run: bool = False, say: Callable[[str], None] = print
) -> dict[str, str]:
    """Publica en Tavus lo que cambió. Devuelve ``{slug: "igual" | "publicado vN" | "error…"}``."""
    catalog = get_catalog()
    provider = ctx.conversation_provider
    if not isinstance(provider, TavusProvider) and not dry_run:
        raise ProviderError("off", "UNO_TRAINING_BACKEND debe ser «tavus» para publicar")
    outcome: dict[str, str] = {}
    now = clock.now()
    published = await provider.list_pals() if isinstance(provider, TavusProvider) else []
    published_ids = {str(p.get("pal_id")) for p in published}
    async with ctx.sessionmaker() as session:
        for scenario in catalog.scenarios:
            digest = catalog.content_hash(scenario)
            current = (
                await session.execute(
                    select(TrainingScenarioVersion)
                    .where(
                        TrainingScenarioVersion.scenario_slug == scenario.slug,
                        TrainingScenarioVersion.retired_at.is_(None),
                    )
                    .order_by(TrainingScenarioVersion.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            # Una clave nueva puede pertenecer a otra cuenta. La referencia local solo sirve
            # si el PAL todavía existe en la cuenta con la que estamos publicando.
            if current and current.content_hash == digest and current.tavus_pal_id in published_ids:
                outcome[scenario.slug] = f"igual (v{current.version}, {current.tavus_pal_id})"
                say(f"= {scenario.doctor.name:22} sin cambios · v{current.version}")
                continue
            last = (
                await session.execute(
                    select(func.max(TrainingScenarioVersion.version)).where(
                        TrainingScenarioVersion.scenario_slug == scenario.slug
                    )
                )
            ).scalar_one()
            version = (last or 0) + 1
            payload = build_pal(catalog, scenario, ctx.settings, version)
            if dry_run:
                outcome[scenario.slug] = f"publicaría v{version}"
                say(
                    f"~ {scenario.doctor.name:22} publicaría v{version} · cara "
                    f"{scenario.casting.face_name} · voz {scenario.casting.voice_name} · "
                    f"{len(payload['system_prompt'])} caracteres de prompt"
                )
                continue
            assert isinstance(provider, TavusProvider)
            reused = _reusable(published, scenario, digest)
            try:
                pal_id = reused or await provider.create_pal(payload)
            except ProviderError as exc:
                outcome[scenario.slug] = f"error: {exc}"
                say(f"✘ {scenario.doctor.name:22} {exc}")
                continue
            if current is not None:
                current.retired_at = now
            session.add(
                TrainingScenarioVersion(
                    scenario_slug=scenario.slug,
                    version=version,
                    content_hash=digest,
                    prompt_version=prompts.PROMPT_VERSION,
                    tavus_pal_id=pal_id,
                    face_id=scenario.casting.face_id,
                    voice_id=scenario.casting.voice_id,
                    published_at=now,
                )
            )
            await session.commit()
            verb = "reutilizado" if reused else "publicado"
            outcome[scenario.slug] = f"{verb} v{version} ({pal_id})"
            say(f"✔ {scenario.doctor.name:22} {verb} v{version} → {pal_id}")
    return outcome


async def cleanup(ctx: AppContext, *, say: Callable[[str], None] = print) -> int:
    """Borra PAL sin versiones vigentes ni prácticas vivas, conservando referencias si falla."""
    provider = ctx.conversation_provider
    if not isinstance(provider, TavusProvider):
        raise ProviderError("off", "UNO_TRAINING_BACKEND debe ser «tavus» para limpiar")
    removed = 0
    async with ctx.sessionmaker() as session:
        retired = (
            (
                await session.execute(
                    select(TrainingScenarioVersion).where(
                        TrainingScenarioVersion.retired_at.is_not(None),
                        TrainingScenarioVersion.tavus_pal_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_pal: dict[str, list[TrainingScenarioVersion]] = defaultdict(list)
        for version in retired:
            assert version.tavus_pal_id is not None
            by_pal[version.tavus_pal_id].append(version)
        for pal_id, versions in by_pal.items():
            in_use = await session.scalar(
                select(TrainingScenarioVersion.id)
                .outerjoin(
                    PracticeAttempt, PracticeAttempt.version_id == TrainingScenarioVersion.id
                )
                .where(
                    TrainingScenarioVersion.tavus_pal_id == pal_id,
                    or_(
                        TrainingScenarioVersion.retired_at.is_(None),
                        PracticeAttempt.status.in_(ACTIVE_STATUSES),
                    ),
                )
                .limit(1)
            )
            if in_use is not None:
                continue
            if not await provider.delete_pal(pal_id):
                say(f"no se borró {pal_id}; se conserva la referencia para reintentar")
                continue
            for version in versions:
                version.tavus_pal_id = None
            # Cada borrado remoto confirmado queda guardado aunque falle uno posterior.
            await session.commit()
            removed += 1
            say(f"borrado {pal_id} ({len(versions)} versiones retiradas)")
    return removed
