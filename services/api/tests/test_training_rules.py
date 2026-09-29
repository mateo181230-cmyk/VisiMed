"""Entrenar: contenido, evaluador por reglas (paridad con el prototipo) y armado del resultado."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uno.modules.training import evaluation, prompts, rules
from uno.modules.training.content import COMPETENCY_IDS, load_catalog
from uno.modules.training.rubric import MAX_TOTAL

REFERENCE = json.loads(
    (Path(__file__).parent / "fixtures" / "training_reference.json").read_text(encoding="utf-8")
)
ROLE = {"medico": "doctor", "visitador": "rep"}


def as_turns(raw: list[dict[str, str]]) -> list[rules.Turn]:
    return [rules.Turn(ROLE[t["role"]], t["content"]) for t in raw]  # type: ignore[arg-type]


# ------------------------------------------------------------------ contenido


def test_catalog_has_the_four_priority_scenarios_in_order() -> None:
    catalog = load_catalog()
    assert [s.slug for s in catalog.scenarios] == [
        "medico_general_indiferenciado",
        "internista_exigente",
        "gastroenterologo_esceptico",
        "formulador_pantoprazol",
    ]
    for scenario in catalog.scenarios:
        assert len(scenario.quiz) == 4
        assert all(sum(o.correct for o in q.options) == 1 for q in scenario.quiz)
        assert all(q.source for q in scenario.quiz), "cada pregunta cita su documento"
        assert scenario.lesson.sources
        assert scenario.casting.face_id.startswith("r")
        assert set(scenario.approval.min_competencies) <= set(COMPETENCY_IDS)


def test_bank_has_an_approved_message_for_every_competency() -> None:
    catalog = load_catalog()
    for scenario in catalog.scenarios:
        for area in COMPETENCY_IDS:
            assert catalog.bank.best_for(area, scenario) is not None, area
    general = catalog.get("medico_general_indiferenciado")
    assert general is not None
    assert catalog.bank.best_for("manejo_objeciones", general).id == "OBJECION_2"  # type: ignore[union-attr]


def test_content_hash_changes_with_what_the_doctor_receives() -> None:
    catalog = load_catalog()
    scenario = catalog.scenarios[0]
    before = catalog.content_hash(scenario)
    changed = scenario.model_copy(update={"base_objection": "Otra objeción"})
    assert catalog.content_hash(changed) != before
    assert catalog.content_hash(scenario) == before


def test_greeting_uses_the_rep_salutation_and_rotates() -> None:
    scenario = load_catalog().scenarios[0]
    assert scenario.greeting(0, "doctora") == "Sí, doctora, cuénteme, pero breve por favor."
    assert scenario.greeting(1, "doctor") == "Lo escucho, pero breve por favor."
    assert scenario.greeting(4, "doctor") == scenario.greeting(0, "doctor")


def test_prompt_carries_behavior_and_guardrails_and_only_the_first_name() -> None:
    catalog = load_catalog()
    scenario = catalog.get("gastroenterologo_esceptico")
    assert scenario is not None
    prompt = prompts.system_prompt(scenario, catalog.common)
    assert "Dr. Camilo Restrepo" in prompt
    assert all(line in prompt for line in scenario.bot_behavior)
    assert "Nunca digas que eres una IA" in prompt
    assert "Hüttling" not in prompt  # el médico no pronuncia la marca (diccionario pendiente)
    context = prompts.attempt_context(
        scenario,
        first_name=prompts.first_name("Ana María Pérez"),
        salutation="doctora",
        attempt_no=2,
    )
    assert "Ana" in context and "Pérez" not in context and "María" not in context
    female = catalog.get("internista_exigente")
    assert female is not None and "una médica" in prompts.system_prompt(female, catalog.common)


# ------------------------------------------------------------------ paridad con el prototipo


@pytest.mark.parametrize("case", REFERENCE, ids=[c["case"] for c in REFERENCE])
def test_rules_match_the_prototype_exactly(case: dict) -> None:  # type: ignore[type-arg]
    result = rules.evaluate(as_turns(case["turns"]), case["scenario"])
    assert result.scores == case["scores"]
    assert result.errors == case["errors"]
    assert result.checks == case["checklist"]
    assert result.areas == case["areas"]
    assert sum(result.scores.values()) == case["total"]


@pytest.mark.parametrize("case", REFERENCE, ids=[c["case"] for c in REFERENCE])
def test_band_and_approval_match_the_prototype(case: dict) -> None:  # type: ignore[type-arg]
    catalog = load_catalog()
    scenario = catalog.get(case["scenario"])
    assert scenario is not None
    built = evaluation.build(
        catalog, scenario, as_turns(case["turns"]), evaluation.QuizSnapshot(4, 4)
    )
    assert built["total"] == case["total"]
    assert built["max"] == MAX_TOTAL
    assert built["band"]["level"] == case["band"]
    assert built["training"]["approved"] == case["approved"]
    assert built["training"]["diagnosis"] == case["diagnosis"]


def test_model_dialogues_keep_their_order_and_the_known_gap() -> None:
    """Bueno 27 > regular 7 > malo 4. El Anexo pide 14–19 para el regular: por eso es preliminar."""
    totals = {c["case"]: c["total"] for c in REFERENCE}
    assert totals["dialogo_bueno"] > totals["dialogo_regular"] > totals["dialogo_malo"]
    assert totals["dialogo_regular"] < 14


# ------------------------------------------------------------------ resultado


def test_result_cites_the_key_moment_and_an_approved_best_response() -> None:
    catalog = load_catalog()
    scenario = catalog.get("medico_general_indiferenciado")
    assert scenario is not None
    bad = next(c for c in REFERENCE if c["case"] == "dialogo_malo")
    built = evaluation.build(catalog, scenario, as_turns(bad["turns"]), None)
    assert built["preliminary"] is True and built["method"] == "reglas"
    assert built["critical_errors"][0]["kind"] == "compliance"  # cumplimiento primero
    moment = built["key_moment"]
    assert moment is not None and "95%" in moment["quote"]
    best = built["best_response"]
    assert best is not None
    assert best["text"] in [m.text for m in catalog.bank.messages]  # nunca un texto inventado
    assert len(built["strengths"]) <= 2 and len(built["improvements"]) <= 2
    assert built["training"]["diagnosis"].startswith("Aún no")  # sin formulario hecho


def test_bank_text_uses_doctora_for_a_female_doctor() -> None:
    catalog = load_catalog()
    female = catalog.get("formulador_pantoprazol")
    male = catalog.get("medico_general_indiferenciado")
    assert female is not None and male is not None
    text = "Totalmente, doctor, y no se trata de desconocer eso. Doctor, gracias."
    assert evaluation.adapt_salutation(text, female) == (
        "Totalmente, doctora, y no se trata de desconocer eso. Doctora, gracias."
    )
    assert evaluation.adapt_salutation(text, male) == text


def test_stt_spellings_of_huttling_still_count() -> None:
    turns = [
        rules.Turn("doctor", "Al final todos son parecidos."),
        rules.Turn(
            "rep",
            "Entiendo, doctor. Por eso, además, ESOMED tiene tecnología Jutlin para proteger el "
            "esomeprazol ácido-lábil del ambiente ácido.",
        ),
    ]
    signals = rules.analyze(turns)
    assert signals.mentions_huttling and signals.huttling_connected
