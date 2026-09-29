"""Trabajador de recordatorios: cada ``reminder_poll_seconds`` envía los avisos que ya tocan.

En producción corre como proceso propio (``uno worker``). En desarrollo puede correr dentro de
la API con ``UNO_EMBEDDED_WORKER=true``. Cuando lleguen las llamadas (E5) se migra a Procrastinate
sobre PostgreSQL (ADR-05); ``run_due_reminders`` es idempotente y no cambia.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from uno import clock
from uno.context import AppContext
from uno.modules.calls.service import run_call_cycle
from uno.modules.notifications.reminders import run_due_reminders
from uno.modules.training.service import run_training_cycle

log = logging.getLogger("uno.worker")


async def run_forever(ctx: AppContext, stop: asyncio.Event) -> None:
    interval = ctx.settings.reminder_poll_seconds
    log.info("trabajador de recordatorios iniciado (cada %s s)", interval)
    while not stop.is_set():
        try:
            stats = await run_due_reminders(ctx, clock.now())
            if stats:
                log.info("recordatorios: %s", stats)
        except Exception:
            log.exception("error en el ciclo de recordatorios")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
    log.info("trabajador de recordatorios detenido")


async def run_calls_forever(ctx: AppContext, stop: asyncio.Event) -> None:
    """Orquestador de llamadas: cada ``call_poll_seconds`` planea, marca y recoge resultados.

    No hace nada si ``UNO_CALL_BACKEND=off`` (valor por defecto): nunca llama a nadie por accidente.
    """
    interval = ctx.settings.call_poll_seconds
    if ctx.settings.call_backend == "off":
        log.info("llamadas apagadas (UNO_CALL_BACKEND=off)")
        return
    log.info(
        "orquestador de llamadas iniciado (%s, cada %s s)", ctx.settings.call_backend, interval
    )
    while not stop.is_set():
        try:
            stats = await run_call_cycle(ctx, clock.now())
            if stats:
                log.info("llamadas: %s", stats)
        except Exception:
            log.exception("error en el ciclo de llamadas")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
    log.info("orquestador de llamadas detenido")


async def run_training_forever(ctx: AppContext, stop: asyncio.Event) -> None:
    """Entrenar: cierra prácticas colgadas y recoge transcripciones. Nada si no hay médico."""
    interval = ctx.settings.training_poll_seconds
    if ctx.conversation_provider is None:
        log.info("médico virtual apagado (UNO_TRAINING_BACKEND=off)")
        return
    log.info("ciclo de práctica iniciado (%s, cada %s s)", ctx.conversation_provider.name, interval)
    while not stop.is_set():
        try:
            stats = await run_training_cycle(ctx, clock.now())
            if stats:
                log.info("práctica: %s", stats)
        except Exception:
            log.exception("error en el ciclo de práctica")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
    log.info("ciclo de práctica detenido")
