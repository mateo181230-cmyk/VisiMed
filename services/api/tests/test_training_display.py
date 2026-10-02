"""El resultado diferencia las técnicas evaluadas de las reservadas a otro nivel."""

from copy import deepcopy
from dataclasses import replace

import pytest

from uno.modules.training import evaluation, rules
from uno.modules.training.content import load_catalog
from uno.modules.training.routes import EvaluationOut

BASIC = "medico_general_indiferenciado"
ASSESSED = {"apertura", "argumentacion", "cierre"}
TURNS = [
    rules.Turn("doctor", "Buenos días, cuénteme."),
    rules.Turn(
        "rep",
        "Buenos días, doctor. Le presento ESOMED, esomeprazol, para pacientes con reflujo. "
        "Para cerrar, tenga en cuenta a ESOMED para ese perfil de paciente.",
    ),
]


@pytest.mark.parametrize("slug", [s.slug for s in load_catalog().scenarios])
def test_only_basic_level_marks_unassessed_techniques(slug: str) -> None:
    catalog = load_catalog()
    scenario = catalog.get(slug)
    assert scenario is not None
    result = evaluation.build(catalog, scenario, TURNS, None)
    flags = {c["id"]: c["evaluated"] for c in result["competencies"]}
    expected = {key: scenario.difficulty != "basico" or key in ASSESSED for key in flags}
    assert flags == expected
    # El esquema público debe conservar la señal que necesita el teléfono.
    public = EvaluationOut.model_validate(result).model_dump()
    assert {c["id"]: c["evaluated"] for c in public["competencies"]} == expected


def test_old_basic_result_gets_display_metadata_without_changing_saved_scores() -> None:
    catalog = load_catalog()
    scenario = catalog.get(BASIC)
    assert scenario is not None
    old = evaluation.build(catalog, scenario, TURNS, None)
    for competency in old["competencies"]:
        competency.pop("evaluated", None)
    original = deepcopy(old)
    display = evaluation.for_display(old)
    assert {c["id"] for c in display["competencies"] if c["evaluated"]} == ASSESSED
    assert display["total"] == old["total"]
    assert display["training"] == old["training"]
    assert old == original


def test_legacy_standard_result_is_not_reclassified_by_current_scenario() -> None:
    catalog = load_catalog()
    scenario = catalog.get(BASIC)
    assert scenario is not None
    original_scenario = scenario.model_copy(update={"difficulty": "intermedio"})
    old = evaluation.build(catalog, original_scenario, TURNS, None)
    old["versions"]["rules"] = "reglas_v1"
    for competency in old["competencies"]:
        competency.pop("evaluated", None)
    display = evaluation.for_display(old)
    assert all(c["evaluated"] for c in display["competencies"])


def test_complete_assessed_techniques_do_not_get_a_generic_improvement(monkeypatch) -> None:
    catalog = load_catalog()
    scenario = catalog.get(BASIC)
    assert scenario is not None
    scored = rules.evaluate(TURNS, BASIC, introductory=True)
    complete = replace(
        scored,
        scores={key: 5 for key in scored.scores},
        errors=[],
        areas=[],
        improvements=[rules.DEFAULT_IMPROVEMENT],
    )
    monkeypatch.setattr(rules, "evaluate", lambda *args, **kwargs: complete)
    result = evaluation.build(catalog, scenario, TURNS, None)
    assert result["improvements"] == []
