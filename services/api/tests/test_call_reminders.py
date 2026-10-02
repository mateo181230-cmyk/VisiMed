"""Recorridos de llamadas previas, reuniones largas y resumen escrito con vencimiento."""

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from uno import clock
from uno.modules.agenda.models import Visit
from uno.modules.calls import service
from uno.modules.calls.models import Call, CallVisit, VisitReport
from uno.modules.calls.provider import FakeOutcome, ProviderError, Turn, canned_data

from .conftest import rep_token
from .helpers import arrived_event, doctor_event, ev, finished_event, post_sync, visit_event
from .test_calls import all_calls, calls_env, cycle, fake, finish_visits, run_until_dialed


async def schedule(env, token, when):
    doctor, doctor_id = doctor_event(env)
    visit, visit_id = visit_event(env, doctor_id=doctor_id, scheduled_at=when)
    body = await post_sync(env, token, [doctor, visit])
    assert all(r["status"] == "applied" for r in body["results"])
    return visit_id


async def read_visit(env, visit_id):
    async with env.ctx.sessionmaker() as session:
        return await session.get(Visit, visit_id)


async def test_1500_meeting_calls_at_1455_once_without_starting_report_deadline(make_env: Any):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        when = clock.now().replace(hour=20, minute=0)  # 15:00 Bogotá
        visit_id = await schedule(env, token, when)
        env.clock.set(when - timedelta(minutes=6))
        await cycle(env)
        assert await all_calls(env) == []
        env.clock.advance(minutes=1)
        await cycle(env)
        request = fake(env).requests[0]
        assert request.dynamic_variables["tipo_llamada"] == "reminder"
        assert "¿ya estás cerca?" in request.dynamic_variables["pregunta_inicial"]
        assert "las 3 de la tarde" in request.dynamic_variables["pregunta_inicial"]
        await cycle(env, advance=20)
        await cycle(env)
        assert len(fake(env).requests) == 1
        visit = await read_visit(env, visit_id)
        assert visit.status == "scheduled" and visit.report_due_at is None
        async with env.ctx.sessionmaker() as session:
            assert await session.get(VisitReport, visit_id) is None


@pytest.mark.parametrize("minutes", [0, 15])
async def test_reminder_preference_is_saved_and_respected(make_env: Any, minutes: int):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        response = await env.client.put(
            "/v1/notifications/preferences",
            headers={
                "Authorization": f"Bearer {token}",
            },
            json={"call_remind_before_min": minutes},
        )
        assert response.status_code == 200
        assert response.json()["call_remind_before_min"] == minutes
        assert 5 in response.json()["remind_options"]
        await schedule(env, token, clock.now() + timedelta(minutes=15))
        await cycle(env)
        assert len(fake(env).requests) == (0 if minutes == 0 else 1)


async def test_rescheduling_or_arriving_cancels_a_queued_reminder(make_env: Any):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        visit_id = await schedule(env, token, clock.now() + timedelta(minutes=5))
        await service.plan_reminders_and_checkins(env.ctx, clock.now())
        await post_sync(
            env,
            token,
            [
                ev(
                    "visit_rescheduled",
                    {
                        "scheduled_at": (clock.now() + timedelta(hours=1)).isoformat(),
                    },
                    visit_id=visit_id,
                )
            ],
        )
        await cycle(env)
        assert fake(env).requests == []
        assert (await all_calls(env))[0].status == "cancelled"


async def test_checkin_at_30_minutes_ongoing_waits_for_finished_then_new_notice(make_env: Any):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        visit_id = await schedule(env, token, clock.now())
        await post_sync(env, token, [arrived_event(visit_id, None)])
        fake(env)._script = lambda req: FakeOutcome(
            data_collection={
                "report_mode": {"value": "ongoing"},
                "meeting_finished": {"value": False},
            }
        )
        await cycle(env, advance=29 * 60 + 59)
        assert fake(env).requests == []
        await cycle(env, advance=1)
        assert fake(env).requests[0].dynamic_variables["tipo_llamada"] == "visit_checkin"
        await cycle(env, advance=20)
        visit = await read_visit(env, visit_id)
        assert visit.status == "in_progress"
        assert visit.finished_at is None and visit.report_due_at is None
        await cycle(env, advance=40 * 60)
        assert len(fake(env).requests) == 1
        assert (await read_visit(env, visit_id)).report_invalid_at is None
        await post_sync(env, token, [finished_event(visit_id, None)])
        fake(env)._script = lambda req: FakeOutcome(data_collection={"report_mode": "deferred"})
        await cycle(env, advance=21)
        notified = clock.now()
        await cycle(env, advance=20)
        visit = await read_visit(env, visit_id)
        assert visit.report_notified_at == notified
        assert visit.report_due_at == notified + timedelta(minutes=30)


async def test_expired_checkin_stays_cancelled_and_next_visit_gets_its_summary(make_env: Any):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        visit_id = await schedule(env, token, clock.now())
        await post_sync(env, token, [arrived_event(visit_id, None)])
        fake(env)._script = lambda req: FakeOutcome(kind="no_answer")
        await cycle(env, advance=30 * 60)
        await cycle(env, advance=20)
        assert (await all_calls(env))[0].status == "queued"

        # El trabajador vuelve después de vencer el plazo y de la ventana de reunión ocupada.
        env.clock.advance(hours=3)
        (next_visit_id,) = await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(data_collection=canned_data())
        for _ in range(4):
            await cycle(env, advance=21)

        calls = await all_calls(env)
        checkins = [call for call in calls if call.purpose == "visit_checkin"]
        assert len(checkins) == 1
        assert checkins[0].status == "cancelled"
        assert (await read_visit(env, visit_id)).report_invalid_at is not None
        assert [req.dynamic_variables["tipo_llamada"] for req in fake(env).requests] == [
            "visit_checkin",
            "summary",
        ]
        async with env.ctx.sessionmaker() as session:
            assert await session.get(VisitReport, next_visit_id) is not None


async def test_cancelled_checkin_is_not_recreated_on_later_cycles(make_env: Any):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        visit_id = await schedule(env, token, clock.now())
        await post_sync(env, token, [arrived_event(visit_id, None)])
        env.clock.advance(minutes=30)
        await service.plan_reminders_and_checkins(env.ctx, clock.now())
        (call,) = await all_calls(env)
        async with env.ctx.sessionmaker() as session:
            stored = await session.get(Call, call.id)
            assert stored is not None
            stored.status = "cancelled"
            link = await session.scalar(select(CallVisit).where(CallVisit.call_id == call.id))
            assert link is not None
            link.live = False
            await session.commit()
        for _ in range(3):
            await cycle(env, advance=20)
        assert len(await all_calls(env)) == 1
        assert fake(env).requests == []


@pytest.mark.parametrize("mode", ["written", "deferred"])
async def test_written_or_no_time_keeps_pending_without_retries_or_reset(make_env: Any, mode: str):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(data_collection={"report_mode": mode})
        await run_until_dialed(env)
        notified = clock.now()
        await cycle(env, advance=20)
        await cycle(env, advance=15 * 60)
        visit = await read_visit(env, visit_id)
        assert visit.report_mode == mode and visit.status == "finished"
        assert visit.report_due_at == notified + timedelta(minutes=30)
        assert len(fake(env).requests) == 1
        env.clock.set(visit.report_due_at)
        await cycle(env)
        visit = await read_visit(env, visit_id)
        assert visit.report_invalid_at == visit.report_due_at
        assert visit.status == "finished" and visit.finished_at is not None


async def test_failed_dial_does_not_start_the_30_minutes(make_env: Any):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env).fail_next_dial = ProviderError("fallo del proveedor")
        await cycle(env, advance=21)
        assert (await read_visit(env, visit_id)).report_due_at is None


async def test_checkin_can_close_an_explicitly_finished_meeting_and_offer_writing(make_env: Any):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        visit_id = await schedule(env, token, clock.now())
        await post_sync(env, token, [arrived_event(visit_id, None)])
        fake(env)._script = lambda req: FakeOutcome(
            data_collection={
                "report_mode": "written",
                "meeting_finished": True,
            }
        )
        await cycle(env, advance=30 * 60)
        notified = clock.now()
        await cycle(env, advance=20)
        visit = await read_visit(env, visit_id)
        assert visit.status == "finished" and visit.finished_at == clock.now()
        assert visit.finish_geo_state == "sin_gps"
        assert visit.report_due_at == notified + timedelta(minutes=30)


async def test_written_summary_without_voice_report_can_be_created_and_confirmed(make_env: Any):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        body = await post_sync(
            env,
            token,
            [
                ev(
                    "report_field_edited",
                    {"field": "summary", "value": "Presenté ESOMED; pidió la ficha."},
                    visit_id=visit_id,
                ),
                ev("report_confirmed", {}, visit_id=visit_id),
            ],
        )
        assert all(r["status"] == "applied" for r in body["results"])
        await cycle(env, advance=21)
        assert fake(env).requests == []
        async with env.ctx.sessionmaker() as session:
            report = await session.get(VisitReport, visit_id)
            assert report.status == "confirmed"
            assert report.fields["summary"]["source"] == "rep_edit"
            assert not report.complete  # un texto libre no inventa los campos estructurados


@pytest.mark.parametrize("before_deadline", [True, False])
async def test_offline_confirmation_uses_actual_event_time_and_late_report_stays_invalid(
    make_env: Any,
    before_deadline: bool,
):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(data_collection={"report_mode": "written"})
        await run_until_dialed(env)
        await cycle(env, advance=20)
        due = (await read_visit(env, visit_id)).report_due_at
        event_time = due - timedelta(seconds=1) if before_deadline else due
        env.clock.set(due + timedelta(minutes=2))
        await cycle(env)
        body = await post_sync(
            env,
            token,
            [
                ev(
                    "report_field_edited",
                    {"field": "summary", "value": "Resumen por escrito"},
                    visit_id=visit_id,
                    ts=event_time,
                ),
                ev("report_confirmed", {}, visit_id=visit_id, ts=event_time),
            ],
        )
        visit = await read_visit(env, visit_id)
        if before_deadline:
            assert body["results"][1]["status"] == "applied"
            assert visit.report_invalid_at is None and visit.status == "confirmed"
        else:
            assert body["results"][1]["reason"] == "report_expired"
            assert visit.report_invalid_at == due and visit.finished_at is not None


async def test_summary_retries_keep_original_deadline(make_env: Any):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(kind="no_answer")
        await run_until_dialed(env)
        due = (await read_visit(env, visit_id)).report_due_at
        await cycle(env, advance=20)
        await cycle(env, advance=5 * 60 + 1)
        assert len(fake(env).requests) == 2
        assert (await read_visit(env, visit_id)).report_due_at == due


@pytest.mark.parametrize("offset", [29 * 60, 30 * 60])
async def test_voice_confirmation_uses_transcript_time_when_analysis_arrives_late(
    make_env: Any,
    offset: int,
):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        data = canned_data()
        data["v1_report_confirmed"] = {"value": True}
        fake(env)._script = lambda req: FakeOutcome(
            delay=timedelta(minutes=31),
            data_collection=data,
            turns=[
                Turn(
                    "agent", "Presentaste ESOMED. ¿Confirmas este resumen de la visita?", offset - 5
                ),
                Turn("user", "Sí, correcto", offset),
            ],
        )
        await run_until_dialed(env)
        dialed_at = clock.now()
        await cycle(env, advance=31 * 60)
        visit = await read_visit(env, visit_id)
        async with env.ctx.sessionmaker() as session:
            report = await session.get(VisitReport, visit_id)
            if offset < 30 * 60:
                assert report.status == "confirmed"
                assert report.confirmed_at == dialed_at + timedelta(seconds=offset)
                assert visit.report_invalid_at is None
            else:
                assert report.status == "ready"
                assert visit.report_invalid_at == visit.report_due_at


async def test_expiration_runs_even_when_telephony_is_disabled(make_env: Any):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        fake(env)._script = lambda req: FakeOutcome(data_collection={"report_mode": "written"})
        await run_until_dialed(env)
        await cycle(env, advance=20)
        due = (await read_visit(env, visit_id)).report_due_at
        env.settings.call_backend = "off"
        env.clock.set(due)
        await cycle(env)
        visit = await read_visit(env, visit_id)
        assert visit.report_invalid_at == due and visit.status == "finished"


async def test_reminder_no_answer_does_not_retry_or_change_visit(make_env: Any):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        visit_id = await schedule(env, token, clock.now() + timedelta(minutes=5))
        fake(env)._script = lambda req: FakeOutcome(kind="no_answer")
        await cycle(env)
        await cycle(env, advance=20)
        await cycle(env, advance=10 * 60)
        assert len(fake(env).requests) == 1
        visit = await read_visit(env, visit_id)
        assert visit.status == "scheduled" and visit.report_due_at is None


async def test_writing_while_call_is_dialing_requires_its_own_confirmation(make_env: Any):
    async with calls_env(make_env) as env:
        token = await rep_token(env)
        (visit_id,) = await finish_visits(env, token)
        data = canned_data() | {"v1_report_confirmed": {"value": True}}
        fake(env)._script = lambda req: FakeOutcome(
            data_collection=data,
            turns=[
                Turn("agent", "¿Confirmas este resumen de la visita?", 10),
                Turn("user", "Sí, correcto", 15),
            ],
        )
        await run_until_dialed(env)
        await post_sync(
            env,
            token,
            [
                ev(
                    "report_field_edited",
                    {
                        "field": "summary",
                        "value": "Mi resumen escrito con una corrección",
                    },
                    visit_id=visit_id,
                )
            ],
        )
        await cycle(env, advance=20)
        async with env.ctx.sessionmaker() as session:
            report = await session.get(VisitReport, visit_id)
            assert report.fields["summary"]["value"] == "Mi resumen escrito con una corrección"
            assert report.status == "ready"
