"""Trainings aus dem JSON von Health Auto Export lesen (Exportversion 2).

Health Auto Export schickt bei der REST-Automation dasselbe JSON wie beim
manuellen Export: {"data": {"metrics": [...], "workouts": [...]}}. Je Training
entstehen eine kleine Zusammenfassung (fuer Sensoren und Liste) und die Details
(Route, Puls je Minute oder Sekunde, Pausen, Kilometer-Splits), die nur die
Karte ueber die WebSocket-API abruft.

Feldnamen und Einheiten nach der Doku von Health Auto Export ("Workouts - JSON
Export Format", Version 2) und einem echten Export vom 31.10.2026. Fehlt ein
Feld, fehlt es auch in der Zusammenfassung; nichts wird geschaetzt.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

KJ_PER_KCAL = 4.184
KM_PER_MILE = 1.609344
M_PER_FOOT = 0.3048

# Kompakte Reihen, damit eine Stunde Route mit einem Punkt pro Sekunde klein
# bleibt. Die Reihenfolge der Felder steht hier und in der Karte.
ROUTE_FIELDS = ("t", "lat", "lon", "alt", "speed", "hacc")
HEART_RATE_FIELDS = ("t", "min", "avg", "max")

# Apple Health vergibt UUIDs. Erlaubt sind nur Zeichen, die in HTML und in der
# Karte nichts anrichten koennen und die der Dateiname der Details unveraendert
# uebernimmt (storage._SAFE), damit zwei IDs nie dieselbe Datei treffen. Alles
# andere verwirft der Parser, statt es zu speichern.
_WORKOUT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


class WorkoutError(ValueError):
    """Ein Training ohne die Pflichtfelder id und start."""


def parse_time(value: Any) -> datetime | None:
    """Zeit wie "2026-10-31 15:30:04 +0100" (HAE) oder ISO 8601."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        parsed = dt_util.parse_datetime(value)
        if parsed is not None and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
        return parsed


def _ts(value: Any) -> int | None:
    parsed = parse_time(value)
    return int(parsed.timestamp()) if parsed else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        # JSON erlaubt beliebig grosse ganze Zahlen
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _qty(obj: Any) -> tuple[float | None, str]:
    """{"qty": 2.9, "units": "km"} -> (2.9, "km")."""
    if isinstance(obj, dict):
        return _number(obj.get("qty")), str(obj.get("units") or "")
    return _number(obj), ""


def _km(obj: Any) -> float | None:
    value, unit = _qty(obj)
    if value is None:
        return None
    unit = unit.lower()
    if unit in ("mi", "mile", "miles"):
        return value * KM_PER_MILE
    if unit == "m":
        return value / 1000
    return value


def _kmh(obj: Any) -> float | None:
    """Tempo in km/h; HAE schreibt "km/hr", "kmph", "mph" oder nur "km"."""
    value, unit = _qty(obj)
    if value is None:
        return None
    unit = unit.lower()
    if unit in ("mph", "mi/hr", "mi/h"):
        return value * KM_PER_MILE
    if unit in ("m/s", "mps"):
        return value * 3.6
    return value


def _kcal(obj: Any) -> float | None:
    value, unit = _qty(obj)
    if value is None:
        return None
    return value / KJ_PER_KCAL if unit.lower() == "kj" else value


def _meter(obj: Any) -> float | None:
    value, unit = _qty(obj)
    if value is None:
        return None
    return value * M_PER_FOOT if unit.lower() in ("ft", "feet") else value


def _celsius(obj: Any) -> float | None:
    value, unit = _qty(obj)
    if value is None:
        return None
    return (value - 32) * 5 / 9 if unit.lower() in ("degf", "f", "°f") else value


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def parse_route(points: Any) -> list[list[Any]]:
    """Route als Reihen [t, lat, lon, alt, speed m/s, horizontale Genauigkeit]."""
    route: list[list[Any]] = []
    if not isinstance(points, list):
        return route
    for point in points:
        if not isinstance(point, dict):
            continue
        lat = _number(point.get("latitude", point.get("lat")))
        lon = _number(point.get("longitude", point.get("lon")))
        t = _ts(point.get("timestamp"))
        if lat is None or lon is None or t is None:
            continue
        speed = _number(point.get("speed"))
        route.append(
            [
                t,
                round(lat, 6),
                round(lon, 6),
                _round(_number(point.get("altitude")), 1),
                None if speed is None or speed < 0 else round(speed, 2),
                _round(_number(point.get("horizontalAccuracy")), 1),
            ]
        )
    route.sort(key=lambda row: row[0])
    return route


def parse_heart_rate(samples: Any) -> list[list[Any]]:
    """Puls als Reihen [t, min, avg, max]; Version 1 hat nur "qty"."""
    rows: list[list[Any]] = []
    if not isinstance(samples, list):
        return rows
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        t = _ts(sample.get("date"))
        avg = _number(sample.get("Avg", sample.get("qty")))
        if t is None or avg is None:
            continue
        low = _number(sample.get("Min"))
        high = _number(sample.get("Max"))
        rows.append(
            [
                t,
                round(low if low is not None else avg, 1),
                round(avg, 1),
                round(high if high is not None else avg, 1),
            ]
        )
    rows.sort(key=lambda row: row[0])
    return rows


def _series(samples: Any, convert=None) -> list[list[Any]]:
    """Reihen [t, Wert] aus {"date", "qty", "units"}, z. B. Schritte je Minute."""
    rows: list[list[Any]] = []
    if not isinstance(samples, list):
        return rows
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        t = _ts(sample.get("date"))
        value = convert(sample) if convert else _number(sample.get("qty"))
        if t is None or value is None:
            continue
        rows.append([t, round(value, 2)])
    rows.sort(key=lambda row: row[0])
    return rows


def parse_pauses(events: Any, end: int | None) -> list[list[int]]:
    """Pausen als [Beginn, Ende] aus den Ereignissen "pause" und "resume"."""
    marks: list[tuple[int, str]] = []
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            t = _ts(event.get("start"))
            if kind in ("pause", "resume") and t is not None:
                marks.append((t, kind))
    marks.sort()
    pauses: list[list[int]] = []
    begin: int | None = None
    for t, kind in marks:
        if kind == "pause" and begin is None:
            begin = t
        elif kind == "resume" and begin is not None:
            pauses.append([begin, t])
            begin = None
    if begin is not None and end is not None and end > begin:
        pauses.append([begin, end])
    return pauses


def _pause_seconds(pauses: list[list[int]], start: int, end: int) -> int:
    return sum(
        max(0, min(end, b) - max(start, a)) for a, b in pauses if b > start and a < end
    )


def parse_splits(
    blocks: Any, heart_rate: list[list[Any]], pauses: list[list[int]]
) -> list[dict[str, Any]]:
    """Kilometer-Splits von Apple (Block mit targetDistance 1 km)."""
    if not isinstance(blocks, list):
        return []
    block = next(
        (
            b
            for b in blocks
            if isinstance(b, dict)
            and isinstance(b.get("targetDistance"), dict)
            and str(b["targetDistance"].get("units", "")).lower() == "km"
            and _number(b["targetDistance"].get("qty")) == 1
        ),
        None,
    )
    if block is None or not isinstance(block.get("items"), list):
        return []
    splits: list[dict[str, Any]] = []
    for item in block["items"]:
        if not isinstance(item, dict):
            continue
        start, end = _ts(item.get("start")), _ts(item.get("end"))
        if start is None or end is None:
            continue
        metrics = item.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        distance, _ = _qty(metrics.get("distance"))
        speed, _ = _qty(metrics.get("speed"))
        hr_max, _ = _qty(metrics.get("heartRateMaximum"))
        active = _number(item.get("activeDuration"))
        if active is None:
            active = float(end - start - _pause_seconds(pauses, start, end))
        in_split = [row[2] for row in heart_rate if start <= row[0] < end]
        splits.append(
            {
                "start": start,
                "end": end,
                "distance_m": _round(distance, 1),
                "active_s": round(active),
                "speed_kmh": _round(speed * 3.6 if speed is not None else None, 2),
                "hr_avg": _round(sum(in_split) / len(in_split), 1)
                if in_split
                else None,
                "hr_max": _round(hr_max, 0),
            }
        )
    return splits


def parse_workout(raw: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ein Training -> (Zusammenfassung, Details)."""
    if not isinstance(raw, dict):
        raise WorkoutError("kein Objekt")
    workout_id = raw.get("id")
    start_dt = parse_time(raw.get("start"))
    if not isinstance(workout_id, str) or not workout_id or start_dt is None:
        raise WorkoutError("id oder start fehlt")
    if not _WORKOUT_ID.fullmatch(workout_id):
        raise WorkoutError("id mit unerlaubten Zeichen oder zu lang")
    end_dt = parse_time(raw.get("end"))
    start = int(start_dt.timestamp())
    end = int(end_dt.timestamp()) if end_dt else None

    route = parse_route(raw.get("route"))
    heart_rate = parse_heart_rate(raw.get("heartRateData"))
    pauses = parse_pauses(raw.get("events"), end)
    splits = parse_splits(raw.get("splits"), heart_rate, pauses)

    duration = _number(raw.get("duration"))
    elapsed = None
    activities = raw.get("activities")
    for activity in activities if isinstance(activities, list) else []:
        if isinstance(activity, dict):
            elapsed = _number(activity.get("elapsedDuration")) or elapsed
    if elapsed is None and end is not None:
        elapsed = float(end - start)
    distance = _km(raw.get("distance"))
    speed = _kmh(raw.get("speed")) or _kmh(raw.get("avgSpeed"))
    heart = raw.get("heartRate") if isinstance(raw.get("heartRate"), dict) else {}
    hr_avg, _ = _qty(raw.get("avgHeartRate") or heart.get("avg"))
    hr_max, _ = _qty(raw.get("maxHeartRate") or heart.get("max"))
    hr_min, _ = _qty(heart.get("min"))
    effort, _ = _qty(raw.get("estimatedEffortScore") or raw.get("effortScore"))
    cadence, _ = _qty(raw.get("stepCadence"))
    intensity, _ = _qty(raw.get("intensity"))
    humidity, _ = _qty(raw.get("humidity"))
    location = raw.get("location")

    summary: dict[str, Any] = {
        "id": workout_id,
        "name": str(raw.get("name") or ""),
        "location": location if isinstance(location, str) else None,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat() if end_dt else None,
        "duration_s": _round(duration, 0),
        "elapsed_s": _round(elapsed, 0),
        "distance_km": _round(distance, 3),
        "speed_kmh": _round(speed, 2),
        "speed_max_kmh": _round(_kmh(raw.get("maxSpeed")), 2),
        "pace_s_per_km": round(duration / distance) if duration and distance else None,
        "hr_avg": _round(hr_avg, 1),
        "hr_min": _round(hr_min, 0),
        "hr_max": _round(hr_max, 0),
        "active_kcal": _round(_kcal(raw.get("activeEnergyBurned")), 0),
        "total_kcal": _round(_kcal(raw.get("totalEnergy")), 0),
        "elevation_up_m": _round(_meter(raw.get("elevationUp")), 1),
        "effort": _round(effort, 1),
        "intensity_met": _round(intensity, 2),
        "cadence_spm": _round(cadence, 0),
        "temperature_c": _round(_celsius(raw.get("temperature")), 1),
        "humidity_pct": _round(humidity, 0),
        "pause_s": sum(b - a for a, b in pauses),
        "route_points": len(route),
        "heart_rate_points": len(heart_rate),
    }
    detail: dict[str, Any] = {
        "id": workout_id,
        "route_fields": list(ROUTE_FIELDS),
        "route": route,
        "heart_rate_fields": list(HEART_RATE_FIELDS),
        "heart_rate": heart_rate,
        "heart_rate_recovery": [
            [row[0], row[2]] for row in parse_heart_rate(raw.get("heartRateRecovery"))
        ],
        "pauses": pauses,
        "splits": splits,
        "steps": _series(raw.get("stepCount")),
        "active_kcal": _series(raw.get("activeEnergy"), _kcal),
    }
    return summary, detail


def parse_payload(payload: Any) -> tuple[list[tuple[dict, dict]], int]:
    """Alle Trainings eines Aufrufs -> ([(Zusammenfassung, Details)], verworfen)."""
    data = payload.get("data") if isinstance(payload, dict) else None
    workouts = data.get("workouts") if isinstance(data, dict) else None
    if not isinstance(workouts, list):
        return [], 0
    parsed: list[tuple[dict, dict]] = []
    rejected = 0
    for raw in workouts:
        try:
            parsed.append(parse_workout(raw))
        except WorkoutError:
            rejected += 1
        except (
            TypeError,
            AttributeError,
            KeyError,
            ValueError,
            ArithmeticError,
        ) as err:
            # Unerwarteter Aufbau eines Trainings: nur dieses verwerfen, nicht
            # den ganzen Aufruf. Ins Log nur der Typ, nie Inhalte.
            _LOGGER.debug("Training verworfen: %s", type(err).__name__)
            rejected += 1
    return parsed, rejected
