"""Importa todos los modelos para que ``Base.metadata`` los conozca (Alembic y pruebas)."""

from uno.db import Base, ChangeCounter
from uno.events import DomainEvent
from uno.modules.agenda.models import Visit, VisitLine
from uno.modules.auth.models import Device, LoginAttempt, RefreshToken, User
from uno.modules.calls.models import Call, CallVisit, VisitReport
from uno.modules.catalog.models import Doctor, Institution, Panel, Product, ProductLine
from uno.modules.notifications.models import (
    EmailVerification,
    NotificationLog,
    NotificationPreference,
    PushSubscription,
)
from uno.modules.sync.models import SyncEvent
from uno.modules.training.models import (
    PracticeAttempt,
    PracticeEvaluation,
    PracticeTurn,
    TrainingProfile,
    TrainingQuizResult,
    TrainingScenarioVersion,
)

__all__ = [
    "Base",
    "Call",
    "CallVisit",
    "ChangeCounter",
    "Device",
    "DomainEvent",
    "Doctor",
    "EmailVerification",
    "Institution",
    "LoginAttempt",
    "NotificationLog",
    "NotificationPreference",
    "Panel",
    "PracticeAttempt",
    "PracticeEvaluation",
    "PracticeTurn",
    "Product",
    "ProductLine",
    "PushSubscription",
    "RefreshToken",
    "SyncEvent",
    "TrainingProfile",
    "TrainingQuizResult",
    "TrainingScenarioVersion",
    "User",
    "Visit",
    "VisitLine",
    "VisitReport",
]
