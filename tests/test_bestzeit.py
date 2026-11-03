"""0.1.20: Schnellster Kilometer beim Radfahren aus dem Tempo von Apple, wie
die Karte "Training" es zeigt; Bestleistung und Balken nennen denselben Wert.

Live 03.11.2026 (Fahrt "Outdoor Radfahren"): km 3 mit 1000 m, active_s 38
(ganze Sekunden) und Apples Tempo 95,4 km/h. Bis 0.1.19 zeigte die Karte
"Bestleistungen" 94,7 km/h (1000 m / 38 s), die Balken 95,4 km/h.
"""

from __future__ import annotations

from datetime import date

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.ha_training.parser import (
    BEST_KM_VERSION,
    best_km,
    best_km_split,
    parse_workout,
)
from custom_components.ha_training.rekorde import compute

from .conftest import payload, post, workout
from .test_rekorde import RECORDS, _records_card

LIVE_KM3 = {"distance_m": 1000.0, "active_s": 38, "speed_kmh": 95.4}


def test_cycling_uses_apple_speed():
    # 3600 / 95,4 = 37,736 s; drei Nachkommastellen
    assert best_km([LIVE_KM3], use_speed=True) == 37.736
    # Daraus wieder 95,4 km/h (wie Balken und Tabelle)
    assert round(3600 / best_km([LIVE_KM3], use_speed=True), 1) == 95.4
    # Ohne Tempo von Apple: aus Zeit und Strecke
    assert best_km([{**LIVE_KM3, "speed_kmh": None}], use_speed=True) == 38.0
    # Schnellster von mehreren
    slow = {"distance_m": 1000.0, "active_s": 72, "speed_kmh": 50.1}
    assert best_km([slow, LIVE_KM3], use_speed=True) == 37.736


def test_foot_keeps_time_without_rounding():
    # Zu Fuss wie min/km in der Karte aus der Zeit, jetzt ohne ganze Sekunden
    split = {"distance_m": 1003.2, "active_s": 581, "speed_kmh": 6.3}
    assert best_km([split]) == 579.147
    # Angefangene Kilometer zaehlen weiter nicht, auch mit Tempo
    assert (
        best_km([{"distance_m": 400.0, "active_s": 30, "speed_kmh": 48.0}], True)
        is None
    )


def test_parser_chooses_by_sport():
    # Testtraining: erster km 660 s aktiv, Apples Tempo 1,25 m/s = 4,5 km/h (800 s)
    walk, _ = parse_workout(workout())
    ride, _ = parse_workout(workout("R", name="Outdoor Radfahren"))
    assert walk["best_km_s"] == 660.0
    assert ride["best_km_s"] == 800.0


async def test_recalculates_stored_once(hass: HomeAssistant, entry, hass_client):
    store = entry.runtime_data.store
    await post(hass_client, payload(workout("R", name="Outdoor Radfahren")))
    # Wie unter 0.1.19 gespeichert: ganze Sekunden aus der Zeit, alte Version
    store.workouts[0]["best_km_s"] = 660
    store.best_km_version = 1
    revision = store.revision
    assert await store.async_backfill_best_km() == 1
    assert store.workouts[0]["best_km_s"] == 800.0
    assert store.best_km_version == BEST_KM_VERSION
    assert store.revision == revision + 1
    # Nur einmal; erneut geschickt gilt das Training als unveraendert
    assert await store.async_backfill_best_km() == 0
    response = await post(hass_client, payload(workout("R", name="Outdoor Radfahren")))
    assert (await response.json())["geaendert"] == 0


async def test_version_survives_restart(hass: HomeAssistant, entry, hass_client):
    store = entry.runtime_data.store
    await post(hass_client, payload(workout("R", name="Outdoor Radfahren")))
    store.workouts[0]["best_km_s"] = 660
    store.best_km_version = 1
    await store._async_save_index()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    store = entry.runtime_data.store
    assert store.workouts[0]["best_km_s"] == 800.0
    assert store.best_km_version == BEST_KM_VERSION
    # Nach dem naechsten Start nicht noch einmal
    store.workouts[0]["best_km_s"] = 1.0
    await store._async_save_index()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.store.workouts[0]["best_km_s"] == 1.0


async def test_without_details_value_stays(hass: HomeAssistant, entry, hass_client):
    store = entry.runtime_data.store
    await post(hass_client, payload(workout("R", name="Outdoor Radfahren")))
    store.workouts[0]["best_km_s"] = 660
    store.workouts[0]["has_detail"] = False
    store.best_km_version = 1
    assert await store.async_backfill_best_km() == 0
    assert store.workouts[0]["best_km_s"] == 660
    assert store.best_km_version == BEST_KM_VERSION


async def test_sensor_shows_one_decimal(hass: HomeAssistant, entry, hass_client):
    await post(hass_client, payload(workout("R", name="Outdoor Radfahren")))
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", "ha_training", f"{entry.entry_id}_record_best_km_cycling"
    )
    assert entity_id is not None
    assert float(hass.states.get(entity_id).state) == 800.0
    options = registry.async_get(entity_id).options["sensor"]
    assert options["suggested_display_precision"] == 1


def test_records_card_matches_bars():
    records = {
        **RECORDS,
        "best_km_cycling": {**RECORDS["best_km_cycling"], "value": 37.736},
    }
    html = _records_card(records=records, config={"sport": "cycling"})["html1"]
    assert "95,4<small>km/h</small>" in html


# 0.1.21: Live nach 0.1.20 stand 37,756 s im Speicher. Das passt nur zu
# Apples Tempo 95,35 km/h (95,34 -> 37,760 s, 95,36 -> 37,752 s). Die Balken
# runden 95,35 zu 95,4, aus den Sekunden zurueckgerechnet wurde 95,349 -> 95,3.
LIVE_9535 = {"distance_m": 1000.0, "active_s": 38, "speed_kmh": 95.35}


def test_split_gives_seconds_and_apple_speed():
    assert best_km_split([LIVE_9535], use_speed=True) == (37.756, 95.35)
    # Zu Fuss und ohne Tempo von Apple: kein km/h
    assert best_km_split([LIVE_9535]) == (38.0, None)
    assert best_km_split([{**LIVE_9535, "speed_kmh": None}], use_speed=True) == (
        38.0,
        None,
    )
    # km/h gehoert zum schnellsten Kilometer
    slow = {"distance_m": 1000.0, "active_s": 72, "speed_kmh": 50.1}
    assert best_km_split([slow, LIVE_9535], use_speed=True) == (37.756, 95.35)
    assert best_km_split([], use_speed=True) == (None, None)


def test_parser_stores_speed_for_cycling_only():
    walk, _ = parse_workout(workout())
    ride, _ = parse_workout(workout("R", name="Outdoor Radfahren"))
    # Testtraining: Apples Tempo des ersten km 1,25 m/s = 4,5 km/h
    assert ride["best_km_kmh"] == 4.5
    assert walk["best_km_kmh"] is None


def test_record_carries_speed():
    ride = {
        "id": "R",
        "name": "Outdoor Radfahren",
        "start": "2026-11-03T08:11:44+01:00",
        "best_km_s": 37.756,
        "best_km_kmh": 95.35,
    }
    walk = {
        "id": "G",
        "name": "Outdoor Spaziergang",
        "start": "2026-10-31T15:30:04+01:00",
        "best_km_s": 1243.0,
        "best_km_kmh": None,
    }
    result = compute([ride, walk], date(2026, 11, 3))
    assert result["best_km_cycling"]["kmh"] == 95.35
    assert "kmh" not in result["best_km_foot"]
    # Distanz und Hoehenmeter ohne km/h
    assert (
        "kmh"
        not in (
            compute([{**ride, "distance_km": 7.6}], date(2026, 11, 3))[
                "distance_cycling"
            ]
        )
    )


def test_records_card_uses_apple_speed():
    rec = {**RECORDS["best_km_cycling"], "value": 37.756}
    with_kmh = {**RECORDS, "best_km_cycling": {**rec, "kmh": 95.35}}
    html = _records_card(records=with_kmh, config={"sport": "cycling"})["html1"]
    assert "95,4<small>km/h</small>" in html
    # Ohne km/h (aelterer Stand): aus den Sekunden, wie bis 0.1.20
    html = _records_card(
        records={**RECORDS, "best_km_cycling": rec}, config={"sport": "cycling"}
    )["html1"]
    assert "95,3<small>km/h</small>" in html


async def test_backfill_adds_speed(hass: HomeAssistant, entry, hass_client):
    store = entry.runtime_data.store
    await post(hass_client, payload(workout("R", name="Outdoor Radfahren")))
    # Wie unter 0.1.20 gespeichert: Sekunden, aber ohne km/h
    del store.workouts[0]["best_km_kmh"]
    store.best_km_version = 2
    assert await store.async_backfill_best_km() == 1
    assert store.workouts[0]["best_km_kmh"] == 4.5
    assert store.best_km_version == 3 == BEST_KM_VERSION
    response = await post(hass_client, payload(workout("R", name="Outdoor Radfahren")))
    assert (await response.json())["geaendert"] == 0


async def test_sensor_attribute_speed(hass: HomeAssistant, entry, hass_client):
    await post(hass_client, payload(workout("R", name="Outdoor Radfahren")))
    await post(hass_client, payload(workout("G")))
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    ride = registry.async_get_entity_id(
        "sensor", "ha_training", f"{entry.entry_id}_record_best_km_cycling"
    )
    walk = registry.async_get_entity_id(
        "sensor", "ha_training", f"{entry.entry_id}_record_best_km_foot"
    )
    assert hass.states.get(ride).attributes["speed_kmh"] == 4.5
    assert "speed_kmh" not in hass.states.get(walk).attributes
