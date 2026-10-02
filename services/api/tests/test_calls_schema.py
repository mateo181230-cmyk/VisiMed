"""Esquema de extracción y frases que se le dicen al agente (sin base de datos)."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from uno.modules.calls.context import (
    VisitBrief,
    build_dynamic_variables,
    doctor_phrase,
    first_name,
    spoken_time,
)
from uno.modules.calls.schema import (
    CORE_FIELDS,
    FIELD_BY_NAME,
    GLOBAL_FIELDS,
    VISIT_FIELDS,
    VISIT_OUTCOMES,
    callback_minutes,
    data_collection_items,
    interview_complete,
    parse_analysis,
)

BOG = ZoneInfo("America/Bogota")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 29, hour, minute, tzinfo=BOG)


def v(value: object) -> dict[str, object]:
    return {"value": value}


# ------------------------------------------------------------------ campos de ElevenLabs


def test_data_collection_fits_the_elevenlabs_limit_and_uses_simple_types() -> None:
    items = data_collection_items()
    assert len(items) == len(CORE_FIELDS) + 2 + len(GLOBAL_FIELDS) <= 25
    assert {i["type"] for i in items.values()} <= {"string", "integer", "boolean"}
    assert "v1_order_taken" in items and "extra_visits_json" in items
    assert items["v1_visit_outcome"]["enum"] == list(VISIT_OUTCOMES)
    assert all(i["description"] for i in items.values())


def test_the_agent_config_in_the_repo_matches_the_schema() -> None:
    from uno.elevenlabs_setup import build_payload, load_config

    config, prompt = load_config()
    payload = build_payload(config, prompt)
    assert set(payload["platform_settings"]["data_collection"]) == set(data_collection_items())
    agent = payload["conversation_config"]["agent"]
    # Todas las variables que usa el guion tienen valor de ejemplo.
    placeholders = set(agent["dynamic_variables"]["dynamic_variable_placeholders"])
    import re

    used = set(re.findall(r"\{\{(\w+)\}\}", prompt + agent["first_message"]))
    assert used <= placeholders, used - placeholders
    assert set(agent["prompt"]["built_in_tools"]) == {"end_call", "voicemail_detection"}


# ------------------------------------------------------------------ lectura


def full_results() -> dict[str, object]:
    return {
        "v1_interest_level": v(4),
        "v1_visit_outcome": v("follow_up_set"),
        "v1_order_taken": v(False),
        "v1_no_order_reason": v("competitor_better"),
        "v1_receptiveness": v("high"),
        "v1_objection": v("  Dice que la   competencia le da mejor precio  "),
        "v1_competitor": v("Nexium"),
        "v1_current_preference": v(""),
        "v1_commitment": v("Enviar material solicitado"),
        "v1_next_action": v("Enviar material y retomar sus preguntas"),
        "v1_next_action_in_days": v(14),
        "v1_samples_delivered": v(False),
        "v1_summary": v("Interés 4/5."),
        "v1_products_discussed": v("ESOMED"),
        "v1_details_json": v(
            json.dumps(
                {
                    "visit_objective": "Explorar necesidades",
                    "discussion": "Hablamos de ESOMED",
                    "receptiveness_score": 4,
                }
            )
        ),
        "extra_visits_json": v("[]"),
        "uncertain_fields": v(""),
        "interview_complete": v(True),
    }


def test_parse_a_complete_visit() -> None:
    (visit,) = parse_analysis(full_results(), 1)
    f = visit.fields
    assert visit.complete and not visit.problems
    assert f["interest_level"].value == 4 and f["interest_level"].confidence == "high"
    assert f["objection"].value == "Dice que la competencia le da mejor precio"  # espacios limpios
    assert f["order_taken"].value is False
    assert f["no_order_reason"].value == "competitor_better"
    assert "competitor" in f and "current_preference" not in f  # vacío = ausente
    assert interview_complete(full_results())


def test_invalid_values_are_dropped_one_by_one_never_the_whole_card() -> None:
    data = full_results() | {
        "v1_interest_level": v(9),  # fuera de 1–5
        "v1_visit_outcome": v("compró_todo"),  # fuera del vocabulario
        "v1_next_action_in_days": v("pronto"),  # no es número
    }
    (visit,) = parse_analysis(data, 1)
    assert {"interest_level", "visit_outcome", "next_action_in_days"} <= set(visit.problems)
    assert "interest_level" not in visit.fields and "no_order_reason" in visit.fields
    assert not visit.complete  # sin interés no hay ficha completa


def test_zero_means_not_determined_and_unknown_is_absence() -> None:
    data = full_results() | {
        "v1_interest_level": v(0),
        "v1_no_order_reason": v("unknown"),
        "v1_receptiveness": v("unknown"),
        "v1_next_action_in_days": v(0),
    }
    (visit,) = parse_analysis(data, 1)
    for name in ("interest_level", "no_order_reason", "receptiveness", "next_action_in_days"):
        assert name not in visit.fields


def test_uncertain_fields_lower_the_confidence() -> None:
    data = full_results() | {"uncertain_fields": v("v1_interest_level, v1_competitor")}
    (visit,) = parse_analysis(data, 1)
    assert visit.fields["interest_level"].confidence == "low"
    assert visit.fields["competitor"].confidence == "low"
    assert visit.fields["visit_outcome"].confidence == "high"


def test_a_false_order_is_kept_because_no_order_is_information() -> None:
    (visit,) = parse_analysis(full_results(), 1)
    assert visit.fields["order_taken"].value is False


def test_extra_visits_are_read_from_the_json_field() -> None:
    extras = [
        {
            "ref": "V2",
            "interest_level": 5,
            "visit_outcome": "order_taken",
            "order_taken": True,
            "products_discussed": "ESOMED",
            "visit_objective": "Presentar",
            "discussion": "Pidió ESOMED",
            "commitment": "Entregar el pedido",
            "next_action": "Entregar el pedido",
            "receptiveness_score": 5,
        },
        {
            "ref": "V3",
            "interest_level": 2,
            "visit_outcome": "rejected",
            "order_taken": False,
            "products_discussed": "ESOMED",
            "visit_objective": "Presentar",
            "discussion": "No quiso hablar de ESOMED",
            "commitment": "No quedaron compromisos",
            "next_action": "No se acordó próximo paso",
            "receptiveness_score": 2,
        },
        {"ref": "V9", "interest_level": 1},  # referencia inexistente: se ignora
    ]
    data = full_results() | {"extra_visits_json": v(json.dumps(extras))}
    first, second, third = parse_analysis(data, 3)
    assert first.complete and second.complete and third.complete
    assert second.fields["order_taken"].value is True and second.position == 2
    assert third.fields["visit_outcome"].value == "rejected"


def test_missing_extra_visits_are_empty_not_invented() -> None:
    data = full_results() | {"extra_visits_json": v("[]")}
    first, second = parse_analysis(data, 2)
    assert first.fields and not second.fields and second.problems == ["missing"]


@pytest.mark.parametrize("bad", ["{no es json", "42", '{"ref": "V2"}', "null", ""])
def test_broken_extra_json_never_raises(bad: str) -> None:
    first, second = parse_analysis(full_results() | {"extra_visits_json": v(bad)}, 2)
    assert first.fields and not second.fields


def test_extra_json_is_ignored_when_there_is_only_one_visit() -> None:
    data = full_results() | {
        "extra_visits_json": v(json.dumps([{"ref": "V2", "interest_level": 5}]))
    }
    assert len(parse_analysis(data, 1)) == 1


def test_a_bare_value_works_like_the_wrapped_one() -> None:
    (visit,) = parse_analysis({"v1_interest_level": 3, "v1_order_taken": "true"}, 1)
    assert visit.fields["interest_level"].value == 3 and visit.fields["order_taken"].value is True


def test_text_is_capped_and_null_words_are_empty() -> None:
    long_text = "x" * 1500
    (visit,) = parse_analysis(
        {"v1_summary": v(long_text), "v1_objection": v("ninguna"), "v1_competitor": v("null")}, 1
    )
    assert len(visit.fields["summary"].value) == 800
    assert "objection" not in visit.fields and "competitor" not in visit.fields


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(30, 30), ("45", 45), (2, 5), (999, 240), (0, None), ("", None), (None, None)],
)
def test_callback_minutes_are_bounded(raw: object, expected: int | None) -> None:
    assert callback_minutes({"callback_in_minutes": v(raw)}) == expected


def test_every_visit_field_has_a_parser_and_a_description() -> None:
    assert set(FIELD_BY_NAME) == {f.name for f in VISIT_FIELDS}
    assert all(len(f.description) > 30 for f in VISIT_FIELDS)


# ------------------------------------------------------------------ lo que se le dice al agente


def test_first_name_and_doctor_phrase() -> None:
    assert first_name("Ana María Pérez") == "Ana"
    assert first_name("  ") == "colega"
    assert doctor_phrase("Dra. Laura Méndez") == "la doctora Laura Méndez"
    assert doctor_phrase("Dr. Carlos Gómez") == "el doctor Carlos Gómez"
    assert doctor_phrase("Doctora Ruiz Toro") == "la doctora Ruiz Toro"
    assert doctor_phrase("Andrés Torres") == "Andrés Torres"


@pytest.mark.parametrize(
    ("hour", "minute", "spoken"),
    [
        (0, 5, "las 12:05 de la mañana"),
        (9, 30, "las 9:30 de la mañana"),
        (12, 0, "las 12 del día"),
        (13, 0, "la una de la tarde"),
        (13, 15, "la 1:15 de la tarde"),
        (15, 15, "las 3:15 de la tarde"),
        (18, 0, "las 6 de la noche"),
        (23, 59, "las 11:59 de la noche"),
    ],
)
def test_spoken_time(hour: int, minute: int, spoken: str) -> None:
    assert spoken_time(at(hour, minute), "America/Bogota") == spoken


def briefs() -> list[VisitBrief]:
    return [
        VisitBrief("Dra. Laura Méndez", "Clínica Central", "GASTRU", at(9, 30)),
        VisitBrief("Dr. Carlos Gómez", "Hospital San Rafael", "GASTRU", at(13)),
        VisitBrief("Andrés Torres", None, "RESPI", at(19, 5)),
    ]


def test_variables_do_not_leak_the_doctor_name_by_default() -> None:
    variables = build_dynamic_variables(
        "Ana María Pérez", briefs(), tz_name="America/Bogota", include_names=False
    )
    text = json.dumps(variables, ensure_ascii=False)
    for private in ("Laura", "Méndez", "Carlos", "Gómez", "Torres"):
        assert private not in text
    assert variables["visitador_nombre"] == "Ana"
    assert variables["num_visitas"] == "3"
    assert "por escrito" in variables["pregunta_inicial"]
    assert "la de las 9:30 de la mañana en Clínica Central" in variables["pregunta_relato"]
    assert (
        variables["visitas_texto"].splitlines()[2]
        == "3. La visita de las 7:05 de la noche (línea RESPI)."
    )


def test_variables_can_name_the_doctor_when_allowed() -> None:
    one = build_dynamic_variables("Ana", briefs()[:1], tz_name="America/Bogota", include_names=True)
    assert (
        one["pregunta_relato"]
        == "Vi que terminaste tu visita con la doctora Laura Méndez. ¿Cómo te fue?"
    )
    many = build_dynamic_variables(
        "Ana", briefs()[1:], tz_name="America/Bogota", include_names=True
    )
    assert many["pregunta_relato"].startswith(
        "Tengo 2 visitas tuyas por reportar. Empecemos con la del doctor Carlos Gómez"
    )


def test_only_the_first_five_visits_are_described() -> None:
    many = [VisitBrief(f"Dr. M{n}", "H", "GASTRU", at(8 + n)) for n in range(8)]
    variables = build_dynamic_variables("Ana", many, tz_name="America/Bogota", include_names=False)
    assert variables["num_visitas"] == "5" and len(variables["visitas_texto"].splitlines()) == 5


def test_a_call_needs_at_least_one_visit() -> None:
    with pytest.raises(ValueError):
        build_dynamic_variables("Ana", [], tz_name="America/Bogota", include_names=False)


def test_prior_commitment_is_context_not_a_current_visit_result() -> None:
    brief = VisitBrief(
        "Dr. Carlos Gómez", "Clínica", "GASTRU", at(13),
        previous_next_action="Llevar una mejor propuesta",
        previous_visit_at=at(9),
    )
    variables = build_dynamic_variables("Ana", [brief], tz_name="America/Bogota", include_names=True)
    assert "Recuerda el pendiente" in variables["pregunta_relato"]
    assert "Llevar una mejor propuesta" in variables["pregunta_relato"]
    assert "no evidencia de cumplimiento" in variables["visitas_texto"]
