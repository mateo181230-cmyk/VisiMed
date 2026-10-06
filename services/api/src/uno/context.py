"""Contenedor de la aplicación: configuración, base de datos, remitentes y proveedores externos."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from uno.config import Settings
from uno.db import make_engine, make_sessionmaker
from uno.modules.calls.provider import ElevenLabsProvider, FakeProvider, VoiceProvider
from uno.modules.journey.provider import (
    JourneyProvider,
    build_journey_provider,
    build_recommendations_provider,
)
from uno.modules.notifications.senders import (
    EmailSender,
    PushSender,
    build_email_sender,
    build_push_sender,
)
from uno.modules.training.provider import (
    ConversationProvider,
    TavusProvider,
)
from uno.modules.training.provider import (
    FakeProvider as FakeConversationProvider,
)


@dataclass
class AppContext:
    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    push_sender: PushSender
    email_sender: EmailSender
    voice_provider: VoiceProvider | None = None  # None: las llamadas están apagadas
    conversation_provider: ConversationProvider | None = None  # None: no hay médico virtual
    journey_provider: JourneyProvider | None = None
    recommendations_provider: JourneyProvider | None = None
    # Estado en memoria del módulo Entrenar (último fallo del proveedor, para no insistir).
    training_state: dict[str, Any] = field(default_factory=dict)


def build_context(
    settings: Settings,
    *,
    push_sender: PushSender | None = None,
    email_sender: EmailSender | None = None,
    voice_provider: VoiceProvider | None = None,
    conversation_provider: ConversationProvider | None = None,
    journey_provider: JourneyProvider | None = None,
    recommendations_provider: JourneyProvider | None = None,
) -> AppContext:
    engine = make_engine(settings.database_url)
    return AppContext(
        settings=settings,
        engine=engine,
        sessionmaker=make_sessionmaker(engine),
        push_sender=push_sender or build_push_sender(settings),
        email_sender=email_sender or build_email_sender(settings),
        voice_provider=voice_provider or build_voice_provider(settings),
        conversation_provider=conversation_provider or build_conversation_provider(settings),
        journey_provider=journey_provider or build_journey_provider(settings),
        recommendations_provider=recommendations_provider
        or build_recommendations_provider(settings),
    )


def build_voice_provider(settings: Settings) -> VoiceProvider | None:
    """``off`` no marca nunca; ``fake`` simula; ``elevenlabs`` llama de verdad."""
    if settings.call_backend == "elevenlabs":
        configured = settings.elevenlabs_phone_channel
        channel = None if configured == "auto" else configured
        return ElevenLabsProvider(
            api_key=settings.elevenlabs_api_key,
            agent_id=settings.elevenlabs_agent_id,
            phone_number_id=settings.elevenlabs_phone_number_id,
            base_url=settings.elevenlabs_base_url,
            channel=channel,
        )
    if settings.call_backend == "fake":
        return FakeProvider()
    return None


def build_conversation_provider(settings: Settings) -> ConversationProvider | None:
    """``off``: sin médico virtual; ``fake``: visita simulada; ``tavus``: médico real en video."""
    if settings.training_backend == "tavus":
        return TavusProvider(api_key=settings.tavus_api_key, base_url=settings.tavus_base_url)
    if settings.training_backend == "fake":
        return FakeConversationProvider()
    return None
