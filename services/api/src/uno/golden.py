"""Banco de escenarios del agente (golden set): conversaciones de texto contra ElevenLabs.

Cada escenario simula a un visitador que cuenta sus visitas; se compara lo que UNO extrae (ya
validado por ``schema.parse_analysis``) con lo esperado. No llama a nadie ni gasta minutos de voz,
así que se puede correr en cada cambio del guion o del esquema (doc 02 T5.5).
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from uno import clock
from uno.elevenlabs_setup import DEFAULT_CONFIG_DIR, ElevenLabsAdmin, ElevenLabsError
from uno.modules.calls.context import VisitBrief, build_dynamic_variables
from uno.modules.calls.provider import ConversationResult, Turn, clean_utterance
from uno.modules.calls.schema import (
    ParsedVisit,
    callback_minutes,
    interview_complete,
    parse_analysis,
)


@dataclass
class Check:
    field: str
    expected: Any
    got: Any
    ok: bool


@dataclass
class ScenarioResult:
    id: str
    transcript: list[tuple[str, str]] = field(default_factory=list)
    visits: list[ParsedVisit] = field(default_factory=list)
    complete: bool = False
    checks: list[Check] = field(default_factory=list)
    leaked: list[str] = field(default_factory=list)
    error: str | None = None
    raw_results: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.ok for c in self.checks) and not self.leaked


def load_scenarios(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or DEFAULT_CONFIG_DIR / "scenarios.json"
    return json.loads(path.read_text(encoding="utf-8"))["scenarios"]


def _briefs(scenario: dict[str, Any], tz_name: str) -> list[VisitBrief]:
    today = clock.local_date(clock.now(), tz_name)
    out = []
    for visit in scenario["visits"]:
        hour, minute = (int(x) for x in visit["at"].split(":"))
        when = datetime(today.year, today.month, today.day, hour, minute, tzinfo=clock.tz(tz_name))
        out.append(VisitBrief(visit["doctor"], visit.get("institution"), visit["line"], when))
    return out


def _matches(expected: Any, got: Any) -> bool:
    options = expected if isinstance(expected, list) else [expected]
    for option in options:
        if option is None and got is None:
            return True
        if isinstance(option, bool) or isinstance(got, bool):
            if option is got:
                return True
        elif isinstance(option, str) and isinstance(got, str):
            if option.lower() in got.lower():
                return True
        elif option == got:
            return True
    return False


def _lookup(
    visits: list[ParsedVisit], complete: bool, key: str, raw: dict[str, Any] | None = None
) -> Any:
    if key == "interview_complete":
        return complete
    if key == "callback_in_minutes":
        return callback_minutes(raw or {})
    m = re.fullmatch(r"v(\d)_(\w+)", key)
    if not m:
        return None
    index, name = int(m.group(1)), m.group(2)
    if index > len(visits):
        return None
    if name == "report_confirmed":
        return visits[index - 1].confirmed
    if name == "complete":
        return visits[index - 1].complete
    value = visits[index - 1].fields.get(name)
    return value.value if value else None


def evaluate(
    scenario: dict[str, Any], raw_results: dict[str, Any], tz_name: str = "America/Bogota"
) -> ScenarioResult:
    result = ScenarioResult(id=scenario["id"], raw_results=raw_results)
    result.visits = parse_analysis(raw_results, len(scenario["visits"]))
    result.complete = interview_complete(raw_results)
    for key, expected in scenario.get("expect", {}).items():
        got = _lookup(result.visits, result.complete, key, raw_results)
        result.checks.append(Check(key, expected, got, _matches(expected, got)))
    content = " ".join(str(f.value) for v in result.visits for f in v.fields.values()).lower()
    forbidden = scenario.get("forbidden_in_report", scenario.get("forbidden_in_summary", []))
    result.leaked = [w for w in forbidden if w.lower() in content]
    return result


def run_scenario(
    admin: ElevenLabsAdmin,
    agent_id: str,
    scenario: dict[str, Any],
    *,
    include_names: bool,
    tz_name: str = "America/Bogota",
) -> ScenarioResult:
    variables = build_dynamic_variables(
        scenario.get("rep", "Carlos Ramírez"),
        _briefs(scenario, tz_name),
        tz_name=tz_name,
        include_names=include_names,
    )
    try:
        response = admin.simulate(
            agent_id, persona=scenario["persona"], dynamic_variables=variables, max_turns=30
        )
    except ElevenLabsError as exc:
        return ScenarioResult(id=scenario["id"], error=str(exc)[:400])
    raw = (response.get("analysis") or {}).get("data_collection_results") or {}
    result = evaluate(scenario, raw, tz_name)
    result.transcript = [
        ("UNO" if turn["role"] == "agent" else "VISITADOR", clean_utterance(turn.get("message")))
        for turn in response.get("simulated_conversation", [])
        if turn.get("message")
    ]
    if "readback_confirmed" in scenario:
        conversation = ConversationResult(
            conversation_id="simulation",
            status="done",
            turns=[
                Turn("agent" if role == "UNO" else "user", text) for role, text in result.transcript
            ],
        )
        got = conversation.has_confirmed_readbacks(len(scenario["visits"]))
        expected = scenario["readback_confirmed"]
        result.checks.append(Check("readback_confirmed", expected, got, expected is got))
    return result


def run_all(
    admin: ElevenLabsAdmin,
    agent_id: str,
    scenarios: list[dict[str, Any]],
    *,
    include_names: bool,
    workers: int = 4,
) -> list[ScenarioResult]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(run_scenario, admin, agent_id, s, include_names=include_names)
            for s in scenarios
        ]
        return [f.result() for f in futures]
