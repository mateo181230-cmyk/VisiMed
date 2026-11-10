"""Fábrica de la aplicación FastAPI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from uno.config import Settings, get_settings
from uno.context import build_context
from uno.modules.agenda import routes as agenda_routes
from uno.modules.auth import routes as auth_routes
from uno.modules.calls import routes as call_routes
from uno.modules.calls.intelligence import router as intelligence_router
from uno.modules.calls.provider import VoiceProvider
from uno.modules.catalog import admin as admin_routes
from uno.modules.journey import routes as journey_routes
from uno.modules.journey.provider import JourneyProvider
from uno.modules.notifications import routes as notification_routes
from uno.modules.notifications.senders import EmailSender, PushSender
from uno.modules.recommendations import routes as recommendation_routes
from uno.modules.sync import routes as sync_routes
from uno.modules.training import routes as training_routes
from uno.modules.territory.routes import router as territory_router
from uno.modules.workflows.routes import router as workflows_router
from uno.modules.marketing.routes import router as marketing_router
from uno.modules.training.provider import ConversationProvider
from uno.worker import run_calls_forever, run_forever, run_training_forever, run_territory_forever

VERSION = "0.1.0"
log = logging.getLogger("uno")


def create_app(
    settings: Settings | None = None,
    *,
    push_sender: PushSender | None = None,
    email_sender: EmailSender | None = None,
    voice_provider: VoiceProvider | None = None,
    conversation_provider: ConversationProvider | None = None,
    journey_provider: JourneyProvider | None = None,
    recommendations_provider: JourneyProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    ctx = build_context(
        settings,
        push_sender=push_sender,
        email_sender=email_sender,
        voice_provider=voice_provider,
        conversation_provider=conversation_provider,
        journey_provider=journey_provider,
        recommendations_provider=recommendations_provider,
    )
    engine = ctx.engine

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        tasks: list[asyncio.Task[None]] = []
        if settings.embedded_worker:
            tasks.append(asyncio.create_task(run_forever(ctx, stop)))
            tasks.append(asyncio.create_task(run_calls_forever(ctx, stop)))
            tasks.append(asyncio.create_task(run_training_forever(ctx, stop)))
            tasks.append(asyncio.create_task(run_territory_forever(ctx, stop)))
        try:
            yield
        finally:
            stop.set()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=5)
            await engine.dispose()

    app = FastAPI(title="UNO Visitas API", version=VERSION, lifespan=lifespan)
    app.state.ctx = ctx

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("referrer-policy", "no-referrer")
        return response

    app.include_router(auth_routes.router)
    app.include_router(agenda_routes.router)
    app.include_router(journey_routes.router)
    app.include_router(sync_routes.router)
    app.include_router(notification_routes.router)
    app.include_router(call_routes.router)
    from uno.modules.calls.browser import router as browser_voice_router
    app.include_router(browser_voice_router)
    app.include_router(intelligence_router)
    app.include_router(recommendation_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(training_routes.router)
    app.include_router(training_routes.webhooks)
    app.include_router(training_routes.manager)
    app.include_router(territory_router)
    from uno.modules.territory.calendar import router as calendar_router
    from uno.modules.territory.demo import router as demo_router
    app.include_router(calendar_router)
    app.include_router(demo_router)
    app.include_router(workflows_router)
    app.include_router(marketing_router)

    @app.get("/salud", tags=["ops"])
    async def health() -> JSONResponse:
        """Estado del sistema, sin datos personales (doc 01 §17)."""
        db_ok = True
        try:
            async with ctx.sessionmaker() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        body = {"estado": "verde" if db_ok else "rojo", "version": VERSION, "base_de_datos": db_ok}
        return JSONResponse(body, status_code=200 if db_ok else 503)

    return app


def app_factory() -> FastAPI:
    """Punto de entrada para ``uvicorn uno.main:app_factory --factory``."""
    return create_app()
