"""Geocerca: distancia y clasificación de una lectura de ubicación (doc 01 §9.3).

La misma regla corre en el teléfono (``apps/web/src/features/geo/geocerca.ts``) y aquí; ambas
pasan la tabla de casos compartida ``docs/contratos/geocerca-casos.json``. Si cambia una regla,
cambia en la tabla y en las dos implementaciones.

Orden de decisión (la tabla del doc no fija la precedencia; se fija así):

1. sin lectura → ``sin_gps`` (sin distancia);
2. ``precision_m > 100`` → ``imprecisa`` (con distancia si hay referencia);
3. sin referencia → ``sin_referencia`` (sin distancia);
4. ``distancia − precision_m <= radio`` → ``verificada``, si no ``lejos``.

La distancia se redondea a metros enteros con la mitad hacia arriba (``floor(x + 0.5)``; no
``round()``, que en Python redondea la mitad al par) y se compara **ya redondeada**, de modo que
Python y TypeScript coinciden en los bordes.
"""

from __future__ import annotations

import math
from typing import Literal, NamedTuple

# Radio medio de la Tierra. Idéntico al del teléfono: si difiere, las distancias no coinciden.
EARTH_RADIUS_M = 6_371_000

# Por encima de este error de lectura no se puede verificar nada.
MAX_USEFUL_PRECISION_M = 100

GeoState = Literal["verificada", "lejos", "imprecisa", "sin_referencia", "sin_gps"]

# Estados de una lectura que el visitador puede mejorar con un reintento («Reintentar ubicación»).
RETRYABLE_STATES: frozenset[str] = frozenset({"sin_gps", "imprecisa"})


class Reading(NamedTuple):
    """Lectura de ubicación del teléfono."""

    lat: float
    lng: float
    precision_m: float


class Reference(NamedTuple):
    """Punto de referencia de la institución."""

    lat: float
    lng: float


def _rad(degrees: float) -> float:
    return degrees * math.pi / 180


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distancia en metros entre dos puntos (fórmula de haversine), sin redondear."""
    d_lat = _rad(lat2 - lat1)
    d_lng = _rad(lng2 - lng1)
    h = math.sin(d_lat / 2) ** 2 + math.cos(_rad(lat1)) * math.cos(_rad(lat2)) * (
        math.sin(d_lng / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def _whole_meters(reading: Reading, reference: Reference) -> int:
    distance = haversine_m(reading.lat, reading.lng, reference.lat, reference.lng)
    return math.floor(distance + 0.5)


def classify(
    reading: Reading | None, reference: Reference | None, radius_m: float
) -> tuple[GeoState, int | None]:
    """Estado de geocerca y distancia entera en metros (``None`` si no aplica)."""
    if reading is None:
        return "sin_gps", None
    if reading.precision_m > MAX_USEFUL_PRECISION_M:
        distance = _whole_meters(reading, reference) if reference is not None else None
        return "imprecisa", distance
    if reference is None:
        return "sin_referencia", None
    distance_m = _whole_meters(reading, reference)
    if distance_m - reading.precision_m <= radius_m:
        return "verificada", distance_m
    return "lejos", distance_m
