"""Server-side capabilities and explicit pilot scope, retaining legacy role compatibility."""

from __future__ import annotations

import uuid

from uno.errors import ApiError

from .models import User


def capabilities(user: User) -> list[str]:
    if user.role == "admin":
        return [
            "territory.read",
            "territory.write",
            "territory.manage",
            "performance.read",
            "training.read",
            "catalog.read",
            "catalog.manage",
            "users.manage",
            "knowledge.manage",
            "marketing.read",
            "marketing.write",
        ]
    if user.role == "rep":
        return ["territory.read", "territory.write", "catalog.read", "marketing.read", "marketing.write"]
    result = ["territory.read", "catalog.read", "training.read"]
    profile = getattr(user, "management_profile", None)
    scope = getattr(user, "pilot_scope", None) or {}
    # This dashboard is granted to the three explicitly scoped managerial profiles.
    # A generic legacy manager or technical admin does not inherit access.
    if profile in ("line", "district", "training") and scope.get("representative_ids") and scope.get("line_ids"):
        result += ["dashboard.read", "marketing.read", "marketing.write"]
    if profile in (None, "line", "district"):
        result += ["territory.write", "territory.manage", "performance.read"]
    if profile in (None, "line"):
        result += ["catalog.manage"]
    if profile in (None, "line", "training"):
        result += ["knowledge.manage"]
    return result


def permits(user: User, capability: str) -> bool:
    return capability in capabilities(user)


def require_capability(user: User, capability: str) -> None:
    if not permits(user, capability):
        raise ApiError(403, "capability_required", "Tu perfil no permite realizar esta acción")


def representative_ids(user: User) -> list[uuid.UUID] | None:
    if user.role == "rep":
        return [user.id]
    if user.role == "admin":
        return None
    scope = getattr(user, "pilot_scope", None)
    if scope is not None or getattr(user, "management_profile", None):
        return [uuid.UUID(x) for x in (scope or {}).get("representative_ids", [])]
    return None


def require_representative(user: User, representative_id: uuid.UUID) -> None:
    allowed = representative_ids(user)
    if allowed is not None and representative_id not in allowed:
        raise ApiError(403, "out_of_scope", "Este registro no pertenece a tu equipo autorizado")


def require_visit_read(user: User, visit) -> None:
    """Demo access applies only to explicitly tagged demonstration visits."""
    demos = (user.pilot_scope or {}).get("demo_representative_ids", [])
    if visit.planned_by == "demo" and permits(user, "dashboard.read") and str(visit.representative_id) in demos:
        return
    require_representative(user, visit.representative_id)


def line_ids(user: User) -> list[uuid.UUID] | None:
    scope = getattr(user, "pilot_scope", None)
    return [uuid.UUID(x) for x in scope.get("line_ids", [])] if scope is not None else None
