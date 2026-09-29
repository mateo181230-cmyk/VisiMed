"""Geocerca en Python: debe dar exactamente lo mismo que el teléfono (doc 01 §9.3).

La tabla de casos es compartida con el frontend (`docs/contratos/geocerca-casos.json`).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from uno.modules.agenda import geofence

# tests/ → services/api → services → raíz del repositorio
REPO_ROOT = Path(__file__).resolve().parents[3]
CASES_FILE = REPO_ROOT / "docs" / "contratos" / "geocerca-casos.json"
CASES = json.loads(CASES_FILE.read_text(encoding="utf-8"))["casos"]


def test_shared_table_has_the_20_cases() -> None:
    assert len(CASES) == 20


@pytest.mark.parametrize("case", CASES, ids=[c["nombre"] for c in CASES])
def test_shared_geofence_cases(case: dict) -> None:  # type: ignore[type-arg]
    lectura = case["lectura"]
    referencia = case["referencia"]
    reading = (
        geofence.Reading(lectura["lat"], lectura["lng"], lectura["precision_m"])
        if lectura is not None
        else None
    )
    reference = (
        geofence.Reference(referencia["lat"], referencia["lng"]) if referencia is not None else None
    )
    state, distance_m = geofence.classify(reading, reference, case["radio_m"])
    assert (state, distance_m) == (case["esperado"]["estado"], case["esperado"]["distancia_m"])


def test_earth_radius_is_the_shared_constant() -> None:
    assert geofence.EARTH_RADIUS_M == 6_371_000
    # Un grado de latitud = R · π / 180
    assert geofence.haversine_m(0, 0, 1, 0) == pytest.approx(6_371_000 * math.pi / 180)
    assert geofence.haversine_m(4.6765, -74.0481, 4.6765, -74.0481) == 0


def test_distance_rounds_half_up_not_bankers(monkeypatch: pytest.MonkeyPatch) -> None:
    """La distancia se redondea con la mitad hacia arriba (round() de Python iría al par) y se
    compara ya redondeada: 150.5 m → 151 → lejos con radio 150 (con round() daría 150 → verificada)."""
    reference = geofence.Reference(0.0, 0.0)
    reading = geofence.Reading(1.0, 1.0, 0)
    for raw, expected in ((150.5, 151), (151.5, 152), (149.5, 150), (0.5, 1)):
        monkeypatch.setattr(geofence, "haversine_m", lambda *_args, raw=raw: raw)
        _state, distance_m = geofence.classify(reading, reference, 150)
        assert distance_m == expected, raw
    monkeypatch.setattr(geofence, "haversine_m", lambda *_args: 150.5)
    assert geofence.classify(reading, reference, 150) == ("lejos", 151)
