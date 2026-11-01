"""Parser: Einheiten, Pausen, Splits, Version 1 und fehlende Felder."""

from __future__ import annotations

import pytest

from custom_components.ha_training.parser import (
    WorkoutError,
    parse_heart_rate,
    parse_pauses,
    parse_route,
    parse_workout,
)

from .conftest import workout


def test_summary_values():
    summary, detail = parse_workout(workout())
    assert summary["distance_km"] == 2.5
    assert summary["duration_s"] == 1620
    assert summary["elapsed_s"] == 1800
    assert summary["active_kcal"] == 100
    assert summary["total_kcal"] == 200
    assert summary["pace_s_per_km"] == 648
    assert summary["effort"] == 3
    assert summary["pause_s"] == 180
    assert summary["route_points"] == len(detail["route"]) == 1620
    assert summary["heart_rate_points"] == 30


def test_detail_rows():
    _, detail = parse_workout(workout())
    t, lat, _lon, _alt, speed, hacc = detail["route"][0]
    assert isinstance(t, int)
    assert round(lat, 4) == 52.5145
    assert speed == 1.2
    assert hacc == 1.2
    assert detail["heart_rate"][0][1:] == [95.0, 100.0, 105.0]
    assert detail["active_kcal"][0][1] == round(14 / 4.184, 2)
    assert detail["heart_rate_recovery"][0][1] == 99.0


def test_splits():
    _, detail = parse_workout(workout())
    first, second = detail["splits"]
    assert first["active_s"] == 660
    assert first["speed_kmh"] == 4.5
    assert first["hr_max"] == 112
    # Zweiter Split ohne activeDuration: Dauer minus Pause (Pause liegt im ersten)
    assert second["active_s"] == 16 * 60
    assert first["hr_avg"] is not None


def test_imperial_units():
    raw = workout()
    raw["distance"] = {"qty": 1.0, "units": "mi"}
    raw["speed"] = {"qty": 2.0, "units": "mph"}
    raw["activeEnergyBurned"] = {"qty": 50, "units": "kcal"}
    raw["elevationUp"] = {"qty": 10, "units": "ft"}
    raw["temperature"] = {"qty": 50, "units": "degF"}
    summary, _ = parse_workout(raw)
    assert summary["distance_km"] == 1.609
    assert summary["speed_kmh"] == 3.22
    assert summary["active_kcal"] == 50
    assert summary["elevation_up_m"] == 3.0
    assert summary["temperature_c"] == 10.0


def test_version_1_keys():
    rows = parse_route(
        [
            {
                "lat": 52.5,
                "lon": 13.3,
                "altitude": 30,
                "timestamp": "2026-10-30 15:00:00 +0100",
            }
        ]
    )
    assert rows == [[1793368800, 52.5, 13.3, 30.0, None, None]]
    hr = parse_heart_rate([{"date": "2026-10-30 15:00:00 +0100", "qty": 101}])
    assert hr == [[1793368800, 101.0, 101.0, 101.0]]


def test_open_pause_ends_with_workout():
    events = [{"type": "pause", "start": "2026-10-30 15:10:00 +0100"}]
    assert parse_pauses(events, 1793370600) == [[1793369400, 1793370600]]


def test_missing_optional_fields():
    raw = {"id": "X", "start": "2026-10-30 15:00:00 +0100", "name": "Yoga"}
    summary, detail = parse_workout(raw)
    assert summary["distance_km"] is None
    assert summary["pace_s_per_km"] is None
    assert detail["route"] == []
    assert detail["splits"] == []


@pytest.mark.parametrize(
    "raw", [None, {}, {"id": "X"}, {"start": "2026-10-30 15:00:00 +0100"}]
)
def test_required_fields(raw):
    with pytest.raises(WorkoutError):
        parse_workout(raw)


def test_bad_points_are_skipped():
    rows = parse_route(
        [
            {
                "latitude": "x",
                "longitude": 13.3,
                "timestamp": "2026-10-30 15:00:00 +0100",
            },
            {"latitude": 52.5, "longitude": 13.3},
            {
                "latitude": float("nan"),
                "longitude": 13.3,
                "timestamp": "2026-10-30 15:00:00 +0100",
            },
            {
                "latitude": 52.5,
                "longitude": 13.3,
                "speed": -1,
                "timestamp": "2026-10-30 15:00:01 +0100",
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0][4] is None


@pytest.mark.parametrize(
    "workout_id",
    ['x"><img src=x onerror="alert(1)">', "a/b", "a b", "<script>", "X" * 129],
)
def test_unsafe_workout_id_is_rejected(workout_id):
    # Die ID landet in der Auswahl der Karte und im Dateinamen der Details
    with pytest.raises(WorkoutError):
        parse_workout(workout(workout_id))


def test_uuid_workout_id_is_accepted():
    summary, _ = parse_workout(workout("8F3A1C2E-1B2C-4D5E-9F00-0123456789AB"))
    assert summary["id"] == "8F3A1C2E-1B2C-4D5E-9F00-0123456789AB"


def test_unexpected_field_types_keep_workout():
    raw = workout()
    raw["activities"] = 5
    raw["distance"] = {"qty": 10**400, "units": "km"}
    raw["splits"] = [
        {"targetDistance": "1 km"},
        {"targetDistance": {"units": "km", "qty": 1}, "items": 5},
    ]
    summary, detail = parse_workout(raw)
    assert summary["distance_km"] is None
    assert summary["elapsed_s"] == 1800
    assert detail["splits"] == []
    raw["splits"] = [
        {
            "targetDistance": {"units": "km", "qty": 1},
            "items": [{"start": raw["start"], "end": raw["end"], "metrics": []}],
        }
    ]
    _, detail = parse_workout(raw)
    assert len(detail["splits"]) == 1
    assert detail["splits"][0]["distance_m"] is None


def test_unexpected_error_rejects_only_that_workout(monkeypatch):
    from custom_components.ha_training import parser

    real = parser.parse_workout
    calls = iter([TypeError("kaputt"), None])

    def flaky(raw):
        error = next(calls)
        if error:
            raise error
        return real(raw)

    monkeypatch.setattr(parser, "parse_workout", flaky)
    parsed, rejected = parser.parse_payload(
        {"data": {"workouts": [workout("A-1"), workout("A-2")]}}
    )
    assert rejected == 1
    assert [summary["id"] for summary, _ in parsed] == ["A-2"]
