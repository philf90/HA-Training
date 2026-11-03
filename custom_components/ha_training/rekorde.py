"""Bestleistungen und Serien (E4).

Aus den Zusammenfassungen aller gespeicherten Trainings, also auch aelterer,
deren Route schon geloescht ist. Je Sportgruppe (sport.py) getrennt, denn
Kilometer zu Fuss und auf dem Rad lassen sich nicht vergleichen:

- Laengste Distanz: zu Fuss, Rad, Schwimmen
- Schnellster Kilometer (aus den Kilometer-Splits von Apple): zu Fuss, Rad
- Meiste Hoehenmeter: zu Fuss, Rad
- Trainingsserie: Tage in Folge mit mindestens einem Training, jede Sportart.
  Die laufende Serie zaehlt bis heute oder gestern, damit sie morgens vor dem
  Training nicht auf 0 faellt.

Ein Training, das geloescht wird, verliert seine Bestleistung; dann gilt die
naechstbeste.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .parser import parse_time
from .sport import CYCLING, FOOT, SWIMMING, sport_of

# Schluessel -> (Sportgruppe, Feld, groesser ist besser)
RECORDS: dict[str, tuple[str, str, bool]] = {
    "distance_foot": (FOOT, "distance_km", True),
    "best_km_foot": (FOOT, "best_km_s", False),
    "elevation_foot": (FOOT, "elevation_up_m", True),
    "distance_cycling": (CYCLING, "distance_km", True),
    "best_km_cycling": (CYCLING, "best_km_s", False),
    "elevation_cycling": (CYCLING, "elevation_up_m", True),
    "distance_swimming": (SWIMMING, "distance_km", True),
}
STREAK = "streak"
STREAK_LONGEST = "streak_longest"
# Ereignisse (Neues Training, Neue Bestleistung) nur fuer Trainings, die
# hoechstens so lange vorbei sind. Beim ersten Abgleich schickt Health Auto
# Export oft Trainings mehrerer Wochen; die landen trotzdem im Speicher.
MAX_AGE = timedelta(hours=24)


def is_recent(workout: dict[str, Any]) -> bool:
    end = parse_time(workout.get("end")) or parse_time(workout.get("start"))
    return end is not None and dt_util.now() - end <= MAX_AGE


def _record(workout: dict[str, Any], value: float, field: str) -> dict[str, Any]:
    record = {
        "value": value,
        "workout_id": workout.get("id"),
        "name": workout.get("name"),
        "start": workout.get("start"),
    }
    # Schnellster Kilometer beim Rad: Tempo von Apple dazu (0.1.21), damit die
    # Karte nicht aus den Sekunden zurueckrechnet (95,35 -> 95,3 statt 95,4)
    kmh = workout.get("best_km_kmh")
    if field == "best_km_s" and isinstance(kmh, (int, float)) and kmh > 0:
        record["kmh"] = kmh
    return record


def compute(workouts: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """Alle Bestleistungen -> {Schluessel: Rekord oder None, Serien: Tage}."""
    best: dict[str, dict[str, Any] | None] = dict.fromkeys(RECORDS)
    days: set[date] = set()
    for workout in workouts:
        start = parse_time(workout.get("start"))
        if start is not None:
            days.add(dt_util.as_local(start).date())
        sport = sport_of(workout.get("name"))
        for key, (group, field, higher) in RECORDS.items():
            if group != sport:
                continue
            value = workout.get(field)
            if not isinstance(value, (int, float)) or value <= 0:
                continue
            current = best[key]
            # Bei Gleichstand bleibt das fruehere Training der Rekordhalter
            if (
                current is None
                or (higher and value > current["value"])
                or (not higher and value < current["value"])
                or (value == current["value"] and _earlier(workout, current))
            ):
                best[key] = _record(workout, value, field)
    result: dict[str, Any] = dict(best)
    result[STREAK], result[STREAK_LONGEST] = _streaks(days, today)
    return result


def _earlier(workout: dict[str, Any], current: dict[str, Any]) -> bool:
    a, b = parse_time(workout.get("start")), parse_time(current.get("start"))
    return a is not None and b is not None and a < b


def _streaks(days: set[date], today: date) -> tuple[int, int]:
    """(laufende Serie, laengste Serie) in Tagen."""
    longest = 0
    for day in days:
        if day - timedelta(days=1) in days:
            continue  # nicht der erste Tag einer Serie
        length = 1
        while day + timedelta(days=length) in days:
            length += 1
        longest = max(longest, length)
    end = today if today in days else today - timedelta(days=1)
    current = 0
    while end - timedelta(days=current) in days:
        current += 1
    return current, longest


def cached(store: Any, now: Any = None) -> dict[str, Any]:
    """Bestleistungen, je Stand des Speichers und Tag nur einmal berechnet.

    Neun Sensoren lesen dasselbe Ergebnis; ohne Zwischenspeicher liefe die
    Schleife ueber alle Trainings neunmal je Aenderung.
    """
    today = dt_util.as_local(now or dt_util.now()).date()
    key = (store.revision, len(store.workouts), today)
    cache = store.cache.get("rekorde")
    if cache is None or cache[0] != key:
        cache = (key, compute(store.workouts, today))
        store.cache["rekorde"] = cache
    return cache[1]


def improved(
    before: dict[str, Any], after: dict[str, Any], new_ids: set[str]
) -> list[dict[str, Any]]:
    """Neue Bestleistungen durch neue Trainings (fuer das Ereignis).

    Nur wenn es vorher schon einen Rekord gab: das erste Training einer
    Sportart ist keine Bestleistung.
    """
    events = []
    for key in RECORDS:
        old, new = before.get(key), after.get(key)
        if old is None or new is None or new["workout_id"] not in new_ids:
            continue
        if new["workout_id"] == old["workout_id"]:
            continue
        events.append({"record": key, **new, "previous": old["value"]})
    if before.get(STREAK_LONGEST) and after[STREAK_LONGEST] > before[STREAK_LONGEST]:
        events.append(
            {
                "record": STREAK_LONGEST,
                "value": after[STREAK_LONGEST],
                "previous": before[STREAK_LONGEST],
            }
        )
    return events
