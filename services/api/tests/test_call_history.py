from datetime import timedelta
from typing import Any

from uno import clock
from uno.db import next_change_seq
from uno.ids import uuid7
from uno.modules.agenda.models import Visit, VisitLine
from uno.modules.calls.models import VisitReport
from uno.modules.calls.service import previous_followup

from .conftest import make_user, rep_token
from .helpers import get_state
from .test_calls import calls_env, finish_visits


async def test_history_is_confirmed_and_scoped_to_rep_doctor_and_discussed_line(make_env: Any) -> None:
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (old_id,) = await finish_visits(env, token)
        other_rep = await make_user(env, phone="+573001234555")
        now = clock.now()
        async with env.ctx.sessionmaker() as session:
            old = await session.get(Visit, old_id)
            assert old
            old.status = "confirmed"
            fields = {
                k: {"value": v, "confidence": "high", "source": "rep_edit"}
                for k, v in {
                    "products_discussed": "GASTRU", "visit_objective": "Presentar propuesta",
                    "discussion": "Pidió una mejor propuesta", "commitment": "Preparar propuesta",
                    "next_action": "Llevar una mejor propuesta", "receptiveness_score": 4,
                    "visit_outcome": "follow_up_set",
                }.items()
            }
            session.add(VisitLine(visit_id=old_id, line_id=old.primary_line_id, role="discussed", source="rep_edit"))
            session.add(VisitReport(visit_id=old_id, status="confirmed", complete=True,
                                   fields=fields, created_at=now, updated_at=now, confirmed_at=now))
            current = Visit(id=uuid7(), representative_id=old.representative_id,
                            doctor_id=old.doctor_id, primary_line_id=old.primary_line_id,
                            title="Llamada con historial prueba", scheduled_at=now,
                                created_at=now, updated_at=now, change_seq=await next_change_seq(session))
            session.add(current)
            await session.flush()
            for owner, line, status, action in [
                (other_rep, old.primary_line_id, "confirmed", "Compromiso de otra persona"),
                (old.representative_id, env.lines["RESPI"], "confirmed", "Compromiso de otra línea"),
                (old.representative_id, old.primary_line_id, "ready", "Información sin confirmar"),
            ]:
                previous = Visit(id=uuid7(), representative_id=owner, doctor_id=old.doctor_id,
                                 primary_line_id=line, status="confirmed",
                                 scheduled_at=now-timedelta(minutes=1), created_at=now, updated_at=now)
                session.add(previous)
                await session.flush()
                session.add(VisitLine(visit_id=previous.id,line_id=line,role="discussed",source="rep_edit"))
                session.add(VisitReport(visit_id=previous.id,status=status,complete=True,
                                       fields=fields | {"next_action": {"value":action,"confidence":"high","source":"rep_edit"}},
                                       created_at=now,updated_at=now))
            await session.commit()
            action, previous_at = await previous_followup(session, current)
            assert action == "Llevar una mejor propuesta"
            assert previous_at == old.finished_at
        state = await get_state(env, token)
        assert next(v for v in state["visits"] if v["id"] == str(current.id))["title"] == current.title
