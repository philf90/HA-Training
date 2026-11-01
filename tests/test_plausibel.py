"""Plausible Messwerte (S8) und Minimum/Maximum ohne Spread (F6)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.ha_training.parser import (
    WorkoutError,
    parse_heart_rate,
    parse_route,
    parse_workout,
)

from .conftest import TZ, fmt, payload, post, workout
from .test_karte import js


def _point(lat, lon, t="2026-10-30 15:00:00 +0100", acc=1.0):
    return {
        "latitude": lat,
        "longitude": lon,
        "timestamp": t,
        "horizontalAccuracy": acc,
    }


def test_route_points_outside_coordinates_are_skipped():
    route = parse_route(
        [
            _point(52.5, 13.3),
            _point(95.0, 13.3),
            _point(52.5, -200.0),
            _point(-90.0, 180.0),
            _point(52.5, 13.3, acc=-1.0),
        ]
    )
    assert [(r[1], r[2]) for r in route] == [(52.5, 13.3), (-90.0, 180.0), (52.5, 13.3)]
    # Negative Genauigkeit gilt als unbekannt, der Punkt bleibt
    assert route[-1][5] is None


def test_heart_rate_outside_range_is_skipped():
    rows = parse_heart_rate(
        [
            {"date": "2026-10-30 15:00:00 +0100", "Avg": 100, "Min": 0, "Max": 400},
            {"date": "2026-10-30 15:01:00 +0100", "Avg": 0},
            {"date": "2026-10-30 15:02:00 +0100", "Avg": 400},
            {"date": "2026-10-30 15:03:00 +0100", "Avg": 20, "Max": 300},
        ]
    )
    # Min/Max ausserhalb fallen auf Avg zurueck; Grenzen selbst gelten
    assert [r[1:] for r in rows] == [[100.0, 100.0, 100.0], [20.0, 20.0, 300.0]]


@pytest.mark.parametrize(
    ("field", "value", "key"),
    [
        ("distance", {"qty": -1, "units": "km"}, "distance_km"),
        ("distance", {"qty": 5000, "units": "km"}, "distance_km"),
        ("duration", -60, "duration_s"),
        ("speed", {"qty": 900, "units": "km/hr"}, "speed_kmh"),
        ("avgHeartRate", {"qty": 900, "units": "count/min"}, "hr_avg"),
        ("activeEnergyBurned", {"qty": -5, "units": "kcal"}, "active_kcal"),
        ("elevationUp", {"qty": -3, "units": "m"}, "elevation_up_m"),
        ("estimatedEffortScore", {"qty": 15}, "effort"),
        ("humidity", {"qty": 150, "units": "%"}, "humidity_pct"),
        ("temperature", {"qty": 100, "units": "degC"}, "temperature_c"),
    ],
)
def test_implausible_summary_values_become_missing(field, value, key):
    raw = workout()
    raw[field] = value
    summary, _ = parse_workout(raw)
    assert summary[key] is None


def test_negative_distance_gives_no_pace():
    raw = workout()
    raw["distance"] = {"qty": -2.5, "units": "km"}
    summary, _ = parse_workout(raw)
    assert summary["pace_s_per_km"] is None


def test_end_before_start_is_dropped():
    raw = workout()
    raw["end"] = fmt(datetime(2026, 10, 30, 14, 0, tzinfo=TZ))
    summary, _ = parse_workout(raw)
    assert summary["end"] is None
    # Gesamtzeit kommt dann aus activities
    assert summary["elapsed_s"] == 1800


def test_start_far_in_future_is_rejected():
    future = dt_util.now() + timedelta(days=3)
    with pytest.raises(WorkoutError):
        parse_workout(workout(start=future, minutes=5, pause=None))
    # Bis zu einem Tag (Zeitzonen, Uhren) geht es
    soon = dt_util.now() + timedelta(hours=12)
    summary, _ = parse_workout(workout(start=soon, minutes=5, pause=None))
    assert summary["id"] == "TEST-0001"


async def test_future_workout_counts_as_rejected(
    hass: HomeAssistant, entry, hass_client
):
    future = dt_util.now() + timedelta(days=30)
    response = await post(
        hass_client, payload(workout("ZUKUNFT", start=future, minutes=5, pause=None))
    )
    body = await response.json()
    assert (body["neu"], body["verworfen"]) == (0, 1)


def test_extent_handles_long_series_without_spread():
    got = js(
        """(() => {
      const many = Array.from({ length: 200000 }, (_, i) => (i % 1000) / 10);
      many[5] = null; many[7] = NaN; many[123456] = -3; many[199999] = 250;
      let spread;
      try { Math.max(...many); spread = "ok"; } catch (e) { spread = e.constructor.name; }
      return { extent: extent(many), empty: extent([null, undefined]), spread };
    })()"""
    )
    assert got["extent"] == [-3, 250]
    assert got["empty"] == [None, None]
    # Belegt das Problem in der Laufzeit der Tests (Node, V8)
    assert got["spread"] == "RangeError"


def test_charts_survive_very_long_workout():
    # 200 000 Puls- und Routenpunkte (rund 55 h bei 1 Hz): _initCharts rechnet
    # die Achsen aus, bevor es zeichnet; mit Math.min(...) gaebe es RangeError
    got = js(
        """(() => {
      const n = 200000, t0 = 1793000000;
      const card = new HaTrainingCard();
      card._hass = { language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" } };
      card._summary = { start: new Date(t0 * 1000).toISOString(), end: new Date((t0 + n) * 1000).toISOString() };
      card._detail = { heart_rate: Array.from({ length: n }, (_, i) => [t0 + i, 90 + (i % 40), 100 + (i % 40), 110 + (i % 40)]), pauses: [] };
      card._points = Array.from({ length: n }, (_, i) => ({ t: t0 + i, v: (i % 60) / 10 }));
      card._charts = [];
      card._color = () => "#000000";  // kein getComputedStyle in Node
      card._initCharts({ querySelector: () => null });
      return "ok";
    })()"""
    )
    assert got == "ok"
