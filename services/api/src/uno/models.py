"""Importa todos los modelos para que ``Base.metadata`` los conozca (Alembic y pruebas)."""

from uno.db import Base, ChangeCounter
from uno.modules.marketing import models as _marketing_models  # noqa: F401
from uno.modules.workflows import models as _workflow_models  # noqa: F401
from uno.modules.territory import models as _territory_models  # noqa: F401
from uno.events import DomainEvent
from uno.modules.agenda.models import Visit, VisitLine
from uno.modules.auth.models import AuthAttemptLock, Device, LoginAttempt, RefreshToken, User
from uno.modules.calls.models import Call, CallVisit, VisitReport
from uno.modules.catalog.models import Doctor, Institution, Panel, Product, ProductLine
from uno.modules.journey.models import PreparationActivity, PreparationMessage, VisitPreparation
from uno.modules.notifications.models import (
    EmailVerification,
    NotificationLog,
    NotificationPreference,
    PushSubscription,
)
from uno.modules.recommendations.models import RecommendationConversation, RecommendationMessage
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
    "AuthAttemptLock",
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
    "PreparationActivity",
    "PreparationMessage",
    "VisitPreparation",
    "PushSubscription",
    "RefreshToken",
    "RecommendationMessage",
    "RecommendationConversation",
    "SyncEvent",
    "TrainingProfile",
    "TrainingQuizResult",
    "TrainingScenarioVersion",
    "User",
    "Visit",
    "VisitLine",
    "VisitReport",
]
