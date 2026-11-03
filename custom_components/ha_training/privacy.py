"""Schutzzone um Zuhause (E8): Punkte der Route im Kreis ausblenden.

Wie die Privatsphaere-Zonen in Sport-Apps, aber fuer die ganze Route: Jeder
Punkt innerhalb des Kreises um Zuhause wird weggelassen, am Anfang, am Ende
und auch mittendrin (0.1.13 kuerzte nur Anfang und Ende; eine Durchfahrt nahe
am Zuhause blieb sichtbar, im echten Einsatz am 03.11.2026 beobachtet).

Gekuerzt wird auf dem Server, die Koordinaten im Kreis verlassen Home
Assistant also nicht. Die gespeicherten Details bleiben vollstaendig; die
Zone wirkt nur auf das, was die Karte und der GPX-Export liefern, und laesst
sich deshalb jederzeit aendern oder abschalten.

Grenze: An jeder Luecke liegt ein sichtbarer Punkt am Rand des Kreises.
Mehrere Routen zusammen verraten so ungefaehr seinen Mittelpunkt. Ein
groesserer Radius macht das ungenauer, aber nicht unmoeglich.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

EARTH_RADIUS_M = 6371008.8


def metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Abstand zweier Punkte (Haversine), wie in der Karte."""
    rad = math.pi / 180
    dp = (lat2 - lat1) * rad
    dl = (lon2 - lon1) * rad
    x = (
        math.sin(dp / 2) ** 2
        + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(dl / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, x)))


def trim_route(
    route: list[list[Any]],
    fields: list[str],
    home: tuple[float, float],
    radius_m: float,
) -> tuple[list[list[Any]], float, float, list[list[float]]]:
    """Route ohne Punkte im Kreis.

    -> (Route, Meter vorn, Meter hinten, Luecken [[Stelle, Meter], ...])

    Meter sind die GPS-Strecke der weggelassenen Teile; bei einer Luecke vom
    letzten sichtbaren Punkt davor bis zum ersten danach, "Stelle" ist der
    Index dieses ersten Punkts in der gekuerzten Route. Die Karte braucht das,
    damit Kilometer-Marken und Umrechnung auf die Distanz von Apple weiter
    stimmen, und trennt die Linie dort.
    """
    if radius_m <= 0 or not route or not {"lat", "lon"} <= set(fields):
        return route, 0.0, 0.0, []
    i_lat, i_lon = fields.index("lat"), fields.index("lon")
    visible = [
        i
        for i, row in enumerate(route)
        if metres(row[i_lat], row[i_lon], *home) > radius_m
    ]
    if not visible:
        # Ganz im Kreis: nichts zeigen
        return [], _length(route, i_lat, i_lon), 0.0, []
    first, last = visible[0], visible[-1]
    start_m = _length(route[: first + 1], i_lat, i_lon)
    end_m = _length(route[last:], i_lat, i_lon)
    gaps = [
        [pos, round(_length(route[a : b + 1], i_lat, i_lon), 1)]
        for pos, (a, b) in enumerate(pairwise(visible), start=1)
        if b - a > 1
    ]
    return [route[i] for i in visible], start_m, end_m, gaps


def _length(rows: list[list[Any]], i_lat: int, i_lon: int) -> float:
    return sum(
        metres(a[i_lat], a[i_lon], b[i_lat], b[i_lon]) for a, b in pairwise(rows)
    )


def apply_zone(
    detail: dict[str, Any], home: tuple[float, float], radius_m: float
) -> dict[str, Any]:
    """Kopie der Details mit gekuerzter Route und Angaben fuer die Karte."""
    if radius_m <= 0:
        return detail
    route, start_m, end_m, gaps = trim_route(
        detail.get("route") or [],
        list(detail.get("route_fields") or []),
        home,
        radius_m,
    )
    return {
        **detail,
        "route": route,
        "privacy": {
            "radius_m": radius_m,
            "start_m": round(start_m, 1),
            "end_m": round(end_m, 1),
            "gaps": gaps,
        },
    }
