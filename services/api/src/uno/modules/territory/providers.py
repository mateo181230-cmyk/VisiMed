"""Adaptadores viales. Nunca convierten distancia recta en tiempo de conducción."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from uno import clock
from uno.config import Settings
from uno.errors import ApiError

from .models import MapCache


def cache_key(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def bogota_point(lat: float, lng: float) -> bool:
    # Filtro de plausibilidad, no certifica una frontera administrativa.
    return 4.45 <= lat <= 4.90 and -74.30 <= lng <= -73.95


async def driving_matrix(
    settings: Settings, session: AsyncSession, points: list[tuple[float, float]]
) -> dict:
    key = cache_key(["car-v1", settings.territory_osrm_url, points])
    cached = await session.get(MapCache, key)
    if cached and cached.expires_at > clock.now():
        return cached.data
    if not settings.territory_osrm_url:
        raise ApiError(
            503,
            "routing_unconfigured",
            "Falta conectar el motor vial. Se conserva la ruta publicada.",
        )
    coordinates = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
            response = await client.get(
                f"{settings.territory_osrm_url.rstrip('/')}/table/v1/driving/{coordinates}",
                params={"annotations": "duration,distance"},
            )
            response.raise_for_status()
            raw = response.json()
        if raw.get("code") != "Ok":
            raise ValueError("invalid matrix")
        for field in ["durations", "distances"]:
            rows = raw.get(field, [])
            if len(rows) != len(points) or any(len(row) != len(points) for row in rows):
                raise ValueError("invalid matrix shape")
            if any(x is None or not math.isfinite(x) or x < 0 for row in rows for x in row):
                raise ValueError("unreachable road point")
        if any(
            x.get("distance", 0) > 300 for x in raw.get("sources", []) + raw.get("destinations", [])
        ):
            raise ValueError("point too far from a drivable road")
        result = {
            "minutes": [[math.ceil(x / 60) for x in row] for row in raw["durations"]],
            "meters": raw["distances"],
            "provider": "OSRM · OpenStreetMap",
            "traffic": False,
            "calculated_at": clock.now().isoformat(),
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise ApiError(
            503,
            "routing_unavailable",
            "No se pudo obtener una matriz vial completa. "
            "Revisa las ubicaciones; la ruta vigente se conserva.",
        ) from None
    if cached:
        cached.data, cached.expires_at = result, clock.now() + timedelta(days=7)
    else:
        session.add(
            MapCache(
                key=key, provider="osrm", data=result, expires_at=clock.now() + timedelta(days=7)
            )
        )
    await session.commit()
    return result


async def geocode(settings: Settings, session: AsyncSession, query: str) -> dict:
    query = " ".join(query.split())
    key = cache_key(["geocode-bogota-v1", query.casefold()])
    cached = await session.get(MapCache, key)
    if cached and cached.expires_at > clock.now():
        return cached.data
    if not settings.territory_geocoder_url:
        raise ApiError(
            503,
            "geocoder_unconfigured",
            "Selecciona y verifica el punto en el mapa; "
            "el buscador de direcciones no está configurado.",
        )
    # Un único contador compartido por procesos. Sin autocompletar ni cargas masivas.
    from uno.db import next_change_seq

    await next_change_seq(session)
    lock = await session.get(MapCache, "geocoder-rate-limit")
    if lock and lock.expires_at > clock.now():
        await session.rollback()
        raise ApiError(
            429, "geocoder_rate_limit", "Espera dos segundos antes de otra búsqueda de dirección"
        )
    if lock:
        lock.expires_at = clock.now() + timedelta(seconds=2)
    else:
        session.add(
            MapCache(
                key="geocoder-rate-limit",
                provider="lock",
                data={},
                expires_at=clock.now() + timedelta(seconds=2),
            )
        )
    await session.commit()
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            r = await client.get(
                settings.territory_geocoder_url.rstrip("/") + "/search",
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": 5,
                    "countrycodes": "co",
                    "bounded": 1,
                    "viewbox": "-74.30,4.90,-73.95,4.45",
                    "addressdetails": 1,
                },
                headers={
                    "User-Agent": "VisiMed/1.0 (+https://novamed.hyperionone.co)",
                    "Accept-Language": "es",
                },
            )
            r.raise_for_status()
            raw = r.json()
        result = {
            "candidates": [
                {
                    "label": x["display_name"],
                    "lat": float(x["lat"]),
                    "lng": float(x["lon"]),
                    "source": "OpenStreetMap / Nominatim",
                }
                for x in raw
            ],
            "requires_confirmation": True,
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise ApiError(
            503,
            "geocoder_unavailable",
            "La búsqueda no está disponible. Puedes verificar la ubicación en el mapa.",
        ) from None
    if cached:
        cached.data, cached.expires_at = result, clock.now() + timedelta(days=30)
    else:
        session.add(
            MapCache(
                key=key,
                provider="nominatim",
                data=result,
                expires_at=clock.now() + timedelta(days=30),
            )
        )
    await session.commit()
    return result


async def road_geometry(settings: Settings, points: list[tuple[float, float]]) -> dict:
    if len(points) < 2:
        return {"geometry": None}
    if not settings.territory_osrm_url:
        raise ApiError(503, "routing_unconfigured", "Motor vial no configurado")
    coords = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                settings.territory_osrm_url.rstrip("/") + f"/route/v1/driving/{coords}",
                params={"overview": "full", "geometries": "geojson", "steps": "false"},
            )
            r.raise_for_status()
            data = r.json()
        return {
            "geometry": data["routes"][0]["geometry"],
            "traffic": False,
            "source": "OpenStreetMap / OSRM",
        }
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        raise ApiError(503, "routing_unavailable", "No se pudo dibujar el recorrido vial") from None
