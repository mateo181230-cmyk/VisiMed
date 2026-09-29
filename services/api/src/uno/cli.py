"""Línea de comandos de administración: ``uno --help``."""

from __future__ import annotations

import asyncio
import base64
import logging
import signal
import uuid
from pathlib import Path

import typer
from sqlalchemy import select

from uno import clock
from uno.config import get_settings
from uno.context import AppContext, build_context
from uno.modules.auth import service as auth_service
from uno.modules.auth.models import User
from uno.modules.notifications import service as notif_service
from uno.security import hash_pin, is_valid_pin, normalize_phone

app = typer.Typer(help="UNO Visitas · administración", no_args_is_help=True)


def _alembic_ini() -> Path:
    """``alembic.ini`` junto al directorio de trabajo (imagen Docker) o al código (desarrollo)."""
    for candidate in (
        Path.cwd() / "alembic.ini",
        Path(__file__).resolve().parents[2] / "alembic.ini",
    ):
        if candidate.exists():
            return candidate
    raise typer.BadParameter("No encuentro alembic.ini; ejecuta el comando desde services/api")


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


async def _with_ctx(fn):  # type: ignore[no-untyped-def]
    ctx = build_context(get_settings())
    try:
        return await fn(ctx)
    finally:
        await ctx.engine.dispose()


@app.command("db-upgrade")
def db_upgrade(revision: str = "head") -> None:
    """Aplica las migraciones a la base de ``UNO_DATABASE_URL``."""
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(_alembic_ini())), revision)
    typer.echo("Base de datos al día.")


@app.command("create-user")
def create_user(
    name: str = typer.Option(..., "--name"),
    phone: str = typer.Option(..., "--phone", help="Formato +573001234567"),
    pin: str = typer.Option(..., "--pin", prompt=True, hide_input=True, help="6 dígitos"),
    role: str = typer.Option("rep", "--role", help="rep | manager | admin"),
    email: str = typer.Option("", "--email", help="Correo para avisos (queda verificado)"),
) -> None:
    """Crea un usuario. El correo, si se da, queda registrado de antemano y verificado."""

    async def go(ctx: AppContext) -> None:
        async with ctx.sessionmaker() as session:
            now = clock.now()
            user = await auth_service.create_user(
                session, ctx.settings, full_name=name, phone=phone, pin=pin, role=role, now=now
            )
            if email:
                await notif_service.admin_register_email(session, user.id, now, email=email)
            else:
                await session.commit()
            typer.echo(f"Usuario creado: {user.full_name} ({user.phone_e164}, {user.role})")

    _run(_with_ctx(go))


@app.command("set-pin")
def set_pin(
    phone: str = typer.Option(..., "--phone"),
    pin: str = typer.Option(..., "--pin", prompt=True, hide_input=True),
) -> None:
    """Cambia el PIN de un usuario."""
    if not is_valid_pin(pin):
        raise typer.BadParameter("El PIN debe tener 6 dígitos")

    async def go(ctx: AppContext) -> None:
        async with ctx.sessionmaker() as session:
            user = (
                await session.execute(select(User).where(User.phone_e164 == normalize_phone(phone)))
            ).scalar_one_or_none()
            if user is None:
                raise typer.BadParameter("No existe ese usuario")
            user.pin_hash = hash_pin(ctx.settings, pin)
            await session.commit()
            typer.echo("PIN actualizado.")

    _run(_with_ctx(go))


@app.command("set-email")
def set_email(
    phone: str = typer.Option(..., "--phone"), email: str = typer.Option(..., "--email")
) -> None:
    """Registra de antemano el correo de avisos de un usuario (queda verificado)."""

    async def go(ctx: AppContext) -> None:
        async with ctx.sessionmaker() as session:
            user = (
                await session.execute(select(User).where(User.phone_e164 == normalize_phone(phone)))
            ).scalar_one_or_none()
            if user is None:
                raise typer.BadParameter("No existe ese usuario")
            await notif_service.admin_register_email(session, user.id, clock.now(), email=email)
            typer.echo("Correo registrado y verificado.")

    _run(_with_ctx(go))


@app.command("set-institution-ref")
def set_institution_ref(
    name: str | None = typer.Option(None, "--name", help="Nombre exacto de la institución"),
    institution_id: str | None = typer.Option(None, "--id", help="Id de la institución (uuid)"),
    lat: float = typer.Option(
        ..., "--lat", min=-90, max=90, help="Latitud del punto de referencia"
    ),
    lng: float = typer.Option(
        ..., "--lng", min=-180, max=180, help="Longitud del punto de referencia"
    ),
    radius: int | None = typer.Option(
        None, "--radius", min=1, help="Radio de la geocerca en metros"
    ),
) -> None:
    """Fija la referencia (lat/lng y radio) de una institución para la geocerca de «Llegué».

    Queda marcada como ``manual`` y sube su ``change_seq``: el teléfono la baja al sincronizar.
    """
    from uno.modules.catalog import service as catalog_service

    try:
        parsed_id = uuid.UUID(institution_id) if institution_id else None
    except ValueError as exc:
        raise typer.BadParameter("--id no es un uuid válido") from exc

    async def go(ctx: AppContext) -> None:
        async with ctx.sessionmaker() as session:
            try:
                institution = await catalog_service.find_institution(
                    session, name=name, institution_id=parsed_id
                )
            except catalog_service.InstitutionLookupError as exc:
                raise typer.BadParameter(str(exc)) from exc
            await catalog_service.set_institution_reference(
                session, institution, lat=lat, lng=lng, radius_m=radius
            )
            typer.echo(
                f"Referencia de «{institution.name}»: {institution.lat}, {institution.lng} "
                f"(radio {institution.radius_m} m)"
            )

    _run(_with_ctx(go))


@app.command("seed-lines")
def seed_lines() -> None:
    """Crea las líneas de producto del piloto (RESPI, OSTRU, GASTRU)."""
    from uno.seed import seed_lines as run

    async def go(ctx: AppContext) -> None:
        typer.echo(f"Líneas creadas: {await run(ctx)}")

    _run(_with_ctx(go))


@app.command("seed-demo")
def seed_demo() -> None:
    """Datos ficticios para probar en local (usuarios de demostración y agenda de hoy)."""
    if get_settings().env == "prod":
        raise typer.BadParameter("seed-demo no se ejecuta en producción")
    from uno.seed import seed_demo as run

    async def go(ctx: AppContext) -> None:
        who = await run(ctx)
        typer.echo(f"Listo. Visitador de demostración: {who['rep']} (el PIN está en uno/seed.py)")

    _run(_with_ctx(go))


@app.command("vapid-generate")
def vapid_generate() -> None:
    """Genera un par de llaves VAPID para Web Push y las imprime como variables de entorno."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    private = b64(key.private_numbers().private_value.to_bytes(32, "big"))
    public = b64(
        key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    typer.echo(f"UNO_VAPID_PUBLIC_KEY={public}")
    typer.echo(f"UNO_VAPID_PRIVATE_KEY={private}")
    typer.echo("# La llave privada es un secreto: va solo en el .env del servidor.")


@app.command("run-reminders")
def run_reminders() -> None:
    """Envía una vez los recordatorios que ya tocan (útil desde un cron)."""
    from uno.modules.notifications.reminders import run_due_reminders

    async def go(ctx: AppContext) -> None:
        typer.echo(str(await run_due_reminders(ctx)))

    _run(_with_ctx(go))


@app.command("worker")
def worker() -> None:
    """Trabajador de recordatorios, llamadas y práctica: corre hasta recibir Ctrl+C."""
    from uno.worker import run_calls_forever, run_forever, run_training_forever

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    async def go(ctx: AppContext) -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # Windows
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
        await asyncio.gather(
            run_forever(ctx, stop), run_calls_forever(ctx, stop), run_training_forever(ctx, stop)
        )

    _run(_with_ctx(go))


# --------------------------------------------------------------------------- ElevenLabs


def _admin():  # type: ignore[no-untyped-def]
    from uno.elevenlabs_setup import ElevenLabsAdmin

    settings = get_settings()
    return ElevenLabsAdmin(settings.elevenlabs_api_key, settings.elevenlabs_base_url), settings


@app.command("elevenlabs-apply")
def elevenlabs_apply() -> None:
    """Crea o actualiza el agente de voz con lo que hay en infra/elevenlabs (por nombre)."""
    from uno.elevenlabs_setup import ElevenLabsError

    admin, _ = _admin()
    try:
        agent_id, created = admin.apply()
    except ElevenLabsError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Agente {'creado' if created else 'actualizado'}: {agent_id}")
    typer.echo(f"Pon UNO_ELEVENLABS_AGENT_ID={agent_id} en ~/.uno-visitas/secrets.env o en el .env")


@app.command("elevenlabs-numbers")
def elevenlabs_numbers() -> None:
    """Lista los números de la cuenta y qué agente usa cada uno."""
    from uno.elevenlabs_setup import ElevenLabsError

    admin, _ = _admin()
    try:
        numbers = admin.list_numbers()
    except ElevenLabsError as exc:
        raise typer.BadParameter(str(exc)) from exc
    for n in numbers:
        agent = (n.get("assigned_agent") or {}).get("agent_name") or "— libre —"
        typer.echo(f"{n['phone_number']}  {n['phone_number_id']}  {n.get('label', ''):24} {agent}")


@app.command("elevenlabs-assign-number")
def elevenlabs_assign_number(
    phone_number_id: str = typer.Option(..., "--phone-number-id"),
    force_reassign: bool = typer.Option(
        False, "--force-reassign", help="Quita el número a otro agente (detiene esa campaña)"
    ),
) -> None:
    """Asigna un número de la cuenta al agente de UNO (no pisa a otro sin --force-reassign)."""
    from uno.elevenlabs_setup import ElevenLabsError, load_config

    admin, settings = _admin()
    try:
        config, _ = load_config()
        agent = admin.find_agent(config["name"])
        if agent is None:
            raise typer.BadParameter("El agente de UNO no existe: corre elevenlabs-apply primero")
        admin.assign_number(phone_number_id, agent["agent_id"], force=force_reassign)
    except ElevenLabsError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Número {phone_number_id} asignado al agente {agent['agent_id']}")
    typer.echo(
        f"Pon UNO_ELEVENLABS_PHONE_NUMBER_ID={phone_number_id} en ~/.uno-visitas/secrets.env"
    )


@app.command("elevenlabs-golden")
def elevenlabs_golden(
    only: str = typer.Option("", "--only", help="Id de un escenario"),
    names: bool = typer.Option(
        False, "--names/--no-names", help="El agente dice el nombre del médico"
    ),
    show: bool = typer.Option(False, "--show", help="Imprime cada conversación completa"),
    workers: int = typer.Option(4, "--workers", min=1, max=8),
    repeat: int = typer.Option(1, "--repeat", min=1, max=10, help="Veces por escenario"),
) -> None:
    """Corre el banco de escenarios (conversaciones de texto, no llama a nadie)."""
    from uno.elevenlabs_setup import ElevenLabsError, load_config
    from uno.golden import load_scenarios, run_all

    admin, _ = _admin()
    config, _ = load_config()
    agent = admin.find_agent(config["name"])
    if agent is None:
        raise typer.BadParameter("El agente de UNO no existe: corre elevenlabs-apply primero")
    scenarios = [s for s in load_scenarios() if not only or s["id"] == only]
    if not scenarios:
        raise typer.BadParameter(f"No hay escenario «{only}»")
    try:
        results = run_all(
            admin, agent["agent_id"], scenarios * repeat, include_names=names, workers=workers
        )
    except ElevenLabsError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if repeat > 1:
        typer.echo("Tasa de aciertos por escenario:")
        failing: list[str] = []
        for scenario in scenarios:
            mine = [r for r in results if r.id == scenario["id"]]
            good = sum(r.passed for r in mine)
            typer.echo(f"  {good}/{len(mine)}  {scenario['id']}")
            for r in mine:
                failing += [f"{r.id}: {c.field} esperado {c.expected!r} · obtenido {c.got!r}"
                            for c in r.checks if not c.ok]
        for line in sorted(set(failing)):
            typer.echo(f"    ✘ {line}")
        total = sum(r.passed for r in results)
        typer.echo(f"\n{total}/{len(results)} conversaciones correctas")
        raise typer.Exit(0 if total == len(results) else 1)
    ok = 0
    for r in results:
        typer.echo(f"\n{'✔' if r.passed else '✘'} {r.id}")
        if r.error:
            typer.echo(f"   ERROR: {r.error}")
        for c in r.checks:
            mark = "  ✔" if c.ok else "  ✘"
            typer.echo(f"  {mark} {c.field}: esperado {c.expected!r} · obtenido {c.got!r}")
        if r.leaked:
            typer.echo(f"   ✘ el resumen contiene datos que no debía: {r.leaked}")
        if show or not r.passed:
            for who, said in r.transcript:
                typer.echo(f"     {who:9}: {said}")
        ok += r.passed
    typer.echo(f"\n{ok}/{len(results)} escenarios correctos")
    raise typer.Exit(0 if ok == len(results) else 1)


# --------------------------------------------------------------------------- llamadas


@app.command("calls-list")
def calls_list(limit: int = typer.Option(20, "--limit", min=1, max=200)) -> None:
    """Últimas llamadas: estado, intento, hora y a quién."""
    from uno.calls_ops import list_calls

    async def go(ctx: AppContext) -> None:
        for line in await list_calls(ctx, limit) or ["(sin llamadas)"]:
            typer.echo(line)

    _run(_with_ctx(go))


@app.command("calls-show")
def calls_show(
    prefix: str = typer.Argument(..., help="Primeros caracteres del id de la llamada"),
) -> None:
    """Detalle de una llamada: fichas por visita y transcripción (datos personales: solo admin)."""
    from uno.calls_ops import show_call

    async def go(ctx: AppContext) -> None:
        for line in await show_call(ctx, prefix):
            typer.echo(line)

    _run(_with_ctx(go))


@app.command("calls-run-once")
def calls_run_once() -> None:
    """Corre un ciclo del orquestador de llamadas (planear, marcar, recoger resultados)."""
    from uno.modules.calls.service import run_call_cycle

    async def go(ctx: AppContext) -> None:
        typer.echo(str(await run_call_cycle(ctx)))

    _run(_with_ctx(go))


@app.command("call-test")
def call_test(
    phone: str = typer.Option(..., "--phone", help="Tu celular, formato +573001234567"),
    visits: int = typer.Option(1, "--visits", min=1, max=3, help="Cuántas visitas reportar"),
    names: bool = typer.Option(
        False, "--names/--no-names", help="El agente dice el nombre del médico de prueba"
    ),
    timeout_min: int = typer.Option(6, "--timeout", min=1, max=30, help="Minutos de espera"),
    ignore_window: bool = typer.Option(False, "--ignore-window", help="Llamar fuera de horario"),
    as_rep: str = typer.Option(
        "", "--as-rep", help="Cuenta de la app dueña de las visitas (recibe el resumen)"
    ),
    real: bool = typer.Option(
        False, "--real", help="Llamar de verdad por ElevenLabs aunque el .env tenga fake u off"
    ),
) -> None:
    """Prueba de punta a punta: crea visitas de prueba terminadas y hace sonar TU celular."""
    from uno.calls_ops import run_test_call
    from uno.context import build_voice_provider

    logging.basicConfig(level=logging.WARNING)

    async def go(ctx: AppContext) -> None:
        if real:
            s = ctx.settings
            missing = [
                name
                for name, value in (
                    ("UNO_ELEVENLABS_API_KEY", s.elevenlabs_api_key),
                    ("UNO_ELEVENLABS_AGENT_ID", s.elevenlabs_agent_id),
                    ("UNO_ELEVENLABS_PHONE_NUMBER_ID", s.elevenlabs_phone_number_id),
                )
                if not value
            ]
            if missing:
                raise typer.BadParameter(
                    f"Faltan en ~/.uno-visitas/secrets.env: {', '.join(missing)}"
                )
            s.call_backend = "elevenlabs"
            ctx.voice_provider = build_voice_provider(s)
        ctx.settings.call_include_doctor_names = names
        ok = await run_test_call(
            ctx,
            phone,
            visits,
            timeout_minutes=timeout_min,
            ignore_window=ignore_window,
            say=typer.echo,
            as_rep=as_rep or None,
        )
        raise typer.Exit(0 if ok else 1)

    _run(_with_ctx(go))


# --------------------------------------------------------------------------- Entrenar (Tavus)


@app.command("training-apply")
def training_apply(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Muestra qué publicaría, sin tocar Tavus"
    ),
) -> None:
    """Publica en Tavus los médicos virtuales cuyo contenido cambió (un PAL por versión)."""
    from uno.modules.training.pal import apply
    from uno.modules.training.provider import ProviderError

    async def go(ctx: AppContext) -> None:
        try:
            await apply(ctx, dry_run=dry_run, say=typer.echo)
        except ProviderError as exc:
            raise typer.BadParameter(str(exc)) from exc

    _run(_with_ctx(go))


@app.command("training-cleanup")
def training_cleanup() -> None:
    """Borra en Tavus los PAL de versiones retiradas (solo los de este módulo)."""
    from uno.modules.training.pal import cleanup
    from uno.modules.training.provider import ProviderError

    async def go(ctx: AppContext) -> None:
        try:
            typer.echo(f"PAL borrados: {await cleanup(ctx, say=typer.echo)}")
        except ProviderError as exc:
            raise typer.BadParameter(str(exc)) from exc

    _run(_with_ctx(go))


@app.command("training-check")
def training_check() -> None:
    """¿Puede Tavus crear conversaciones? Prueba sin costo (``test_mode``)."""
    from uno.modules.training.provider import ProviderError, TavusProvider

    async def go(ctx: AppContext) -> None:
        provider = ctx.conversation_provider
        if not isinstance(provider, TavusProvider):
            typer.echo(f"UNO_TRAINING_BACKEND={ctx.settings.training_backend}: no hay Tavus")
            raise typer.Exit(1)
        try:
            problem = await provider.probe()
        except ProviderError as exc:
            problem = exc.code
        messages = {
            None: "Tavus acepta conversaciones: el médico virtual está disponible.",
            "no_credits": "La cuenta de Tavus no tiene créditos de conversación.",
            "auth": "Tavus rechazó la llave (UNO_TAVUS_API_KEY).",
            "not_published": "No hay médicos publicados: corre `uno training-apply`.",
        }
        typer.echo(messages.get(problem, f"Tavus respondió: {problem}"))
        raise typer.Exit(0 if problem is None else 1)

    _run(_with_ctx(go))


@app.command("training-attempts")
def training_attempts(limit: int = typer.Option(20, "--limit", min=1, max=200)) -> None:
    """Últimas prácticas: estado, escenario, puntaje y visitador."""
    from uno.modules.training.models import PracticeAttempt, PracticeEvaluation

    async def go(ctx: AppContext) -> None:
        async with ctx.sessionmaker() as session:
            rows = (
                await session.execute(
                    select(PracticeAttempt, User.full_name, PracticeEvaluation.total)
                    .join(User, User.id == PracticeAttempt.user_id)
                    .outerjoin(
                        PracticeEvaluation, PracticeEvaluation.attempt_id == PracticeAttempt.id
                    )
                    .order_by(PracticeAttempt.created_at.desc())
                    .limit(limit)
                )
            ).all()
        if not rows:
            typer.echo("(sin prácticas)")
        for attempt, name, total in rows:
            score = f"{total}/30" if total is not None else "—"
            typer.echo(
                f"{str(attempt.id)[:8]}  {attempt.created_at:%Y-%m-%d %H:%M}  {attempt.status:13} "
                f"{score:6} {attempt.scenario_slug:30} {name}"
                + (f"  [{attempt.error_code}]" if attempt.error_code else "")
            )

    _run(_with_ctx(go))


if __name__ == "__main__":
    app()
