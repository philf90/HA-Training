"""Langzeitstatistik (E3) mit echtem Recorder: Monat, Woche, Loeschen."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
from unittest.mock import patch

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    get_metadata,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.ha_training import statistik
from custom_components.ha_training.const import SIGNAL_UPDATED
from custom_components.ha_training.statistik import SERIES, build

from .conftest import TZ, payload, post, workout

UTC = timezone.utc


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Recorder vor hass einrichten (Reihenfolge der Fixtures)."""
    yield


def _w(wid, start, km, name="Outdoor Spaziergang", minutes=30):
    return {
        "id": wid,
        "name": name,
        "start": start.isoformat(),
        "distance_km": km,
        "duration_s": minutes * 60,
        "active_kcal": 100,
    }


def test_build_hourly_running_sum():
    workouts = [
        _w("A", datetime(2026, 9, 1, 10, 20, tzinfo=UTC), 2.5),
        _w("B", datetime(2026, 9, 1, 10, 50, tzinfo=UTC), 1.0),
        _w("C", datetime(2026, 10, 3, 8, 5, tzinfo=UTC), 5.0, "Outdoor Radfahren"),
    ]
    series = build(workouts)
    distance = series["distance"]
    # Zeile mit Summe 0 davor, A und B in derselben Stunde
    assert [(r["start"], r["sum"]) for r in distance] == [
        (datetime(2026, 9, 1, 9, tzinfo=UTC), 0.0),
        (datetime(2026, 9, 1, 10, tzinfo=UTC), 3.5),
        (datetime(2026, 10, 3, 8, tzinfo=UTC), 8.5),
    ]
    assert series["workouts"][-1]["sum"] == 3
    assert series["duration"][-1]["sum"] == 90
    assert series["distance_foot"][-1]["sum"] == 3.5
    assert series["distance_cycling"][-1]["sum"] == 5.0
    assert series["distance_swimming"] == []


def test_build_skips_missing_values():
    workouts = [
        {"id": "X", "name": "Yoga", "start": "2026-09-01T10:00:00+00:00"},
        {"id": "Y", "name": "Yoga", "start": None},
    ]
    series = build(workouts)
    assert series["workouts"][-1]["sum"] == 1
    assert series["distance"] == []


async def _months(hass: HomeAssistant, key: str) -> list[float]:
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 8, 1, tzinfo=UTC),
        None,
        {statistik.statistic_id(key)},
        "month",
        None,
        {"change"},
    )
    return [
        round(row["change"], 3) for row in result.get(statistik.statistic_id(key), [])
    ]


async def _rebuild(hass: HomeAssistant, entry) -> None:
    await entry.runtime_data.statistics.async_run_now()
    await async_wait_recording_done(hass)


async def test_month_sums_and_delete(hass: HomeAssistant, entry, hass_client):
    await hass.config.async_set_time_zone("Europe/Berlin")
    september = workout("SEP", datetime(2026, 9, 15, 9, 0, tzinfo=TZ))
    october = workout("OKT", datetime(2026, 10, 15, 9, 0, tzinfo=TZ))
    bike = workout(
        "RAD", datetime(2026, 10, 20, 9, 0, tzinfo=TZ), name="Outdoor Radfahren"
    )
    bike["distance"] = {"qty": 20.0, "units": "km"}
    await post(hass_client, payload(september, october, bike))
    await _rebuild(hass, entry)

    assert await _months(hass, "distance") == [2.5, 22.5]
    assert await _months(hass, "distance_foot") == [2.5, 2.5]
    assert await _months(hass, "distance_cycling") == [20.0]
    assert await _months(hass, "workouts") == [1, 2]

    # Loeschen nimmt das Training auch aus dem vergangenen Monat
    await hass.services.async_call(
        "ha_training", "delete_workout", {"workout_id": "SEP"}, blocking=True
    )
    await _rebuild(hass, entry)
    assert await _months(hass, "distance") == [22.5]
    assert await _months(hass, "workouts") == [2]


async def test_latecomer_lands_in_its_week(hass: HomeAssistant, entry, hass_client):
    await hass.config.async_set_time_zone("Europe/Berlin")
    monday = workout("MO", datetime(2026, 10, 26, 18, 0, tzinfo=TZ))
    await post(hass_client, payload(monday))
    await _rebuild(hass, entry)
    # Das Training vom Sonntag davor kommt erst danach an
    sunday = workout("SO", datetime(2026, 10, 25, 20, 0, tzinfo=TZ))
    await post(hass_client, payload(sunday))
    await _rebuild(hass, entry)
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 10, 12, tzinfo=UTC),
        None,
        {"ha_training:workouts"},
        "week",
        None,
        {"change"},
    )
    weeks = [row["change"] for row in result["ha_training:workouts"]]
    # Woche ab 19.10. (Sonntag 25.10.) und Woche ab 26.10. je 1
    assert weeks == [1, 1]


async def test_metadata(hass: HomeAssistant, entry, hass_client):
    hass.config.language = "de"
    await post(hass_client, payload(workout()))
    await _rebuild(hass, entry)
    meta = await get_instance(hass).async_add_executor_job(
        partial(get_metadata, hass, statistic_ids={f"ha_training:{k}" for k in SERIES})
    )
    distance = meta["ha_training:distance"][1]
    assert distance["name"] == "Training Distanz"
    assert distance["unit_of_measurement"] == "km"
    assert distance["has_sum"] is True
    energy = meta["ha_training:active_energy"][1]
    # Ohne Einheitenklasse: nicht als Strom im Energie-Dashboard
    assert energy["unit_class"] is None
    # Nie geschwommen: keine Reihe
    assert "ha_training:distance_swimming" not in meta


async def test_changes_schedule_one_rebuild(hass: HomeAssistant, entry):
    calls = []
    original = statistik.async_rebuild

    async def counting(hass_, store):
        calls.append(store)
        return await original(hass_, store)

    with patch.object(statistik, "async_rebuild", counting):
        for _ in range(3):
            async_dispatcher_send(hass, f"{SIGNAL_UPDATED}_{entry.entry_id}", [])
        await hass.async_block_till_done()
        # Vor Ablauf der 10 s noch nichts, auch nicht nach 5 s
        assert calls == []
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
        await hass.async_block_till_done()
        assert calls == []
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
        await hass.async_block_till_done()
    # Drei Signale kurz hintereinander, ein Neuaufbau
    assert len(calls) == 1
