"""0.1.22 (V3): Index-Speicher mit Migration ueber Home Assistant.

Version 1.1 (bis 0.1.21) -> 1.2: Der schnellste Kilometer wird neu gerechnet,
wenn er aus einer Rechnung vor 0.1.21 stammt; die eigene Marke
"best_km_version" aus 0.1.20/0.1.21 entfaellt.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from custom_components.ha_training.const import STORAGE_INDEX
from custom_components.ha_training.storage import IndexStore

from .conftest import payload, post, workout

RIDE = "Outdoor Radfahren"


def _key(entry) -> str:
    return f"{STORAGE_INDEX}.{entry.entry_id}"


async def _old_index(hass, entry, hass_storage, change) -> dict[str, Any]:
    """Index wie von einer aelteren Version gespeichert, dann neu laden."""
    stored = hass_storage[_key(entry)]
    stored["minor_version"] = 1
    for w in stored["data"]["workouts"]:
        change(stored["data"], w)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    return hass_storage[_key(entry)]


def _as_0_1_19(data, w):
    # Ganze Sekunden aus der Zeit, ohne km/h und ohne Marke
    w["best_km_s"] = 660
    w.pop("best_km_kmh", None)


async def test_new_index_is_1_2(hass: HomeAssistant, entry, hass_client, hass_storage):
    await post(hass_client, payload(workout("R", name=RIDE)))
    stored = hass_storage[_key(entry)]
    assert (stored["version"], stored["minor_version"]) == (1, 2)
    assert "best_km_version" not in stored["data"]


async def test_from_0_1_19_recalculates(
    hass: HomeAssistant, entry, hass_client, hass_storage
):
    await post(hass_client, payload(workout("R", name=RIDE)))
    stored = await _old_index(hass, entry, hass_storage, _as_0_1_19)
    workout_ = entry.runtime_data.store.workouts[0]
    # Testtraining: Apples Tempo des ersten km 4,5 km/h = 800 s
    assert workout_["best_km_s"] == 800.0 and workout_["best_km_kmh"] == 4.5
    # Gespeichert als 1.2
    assert stored["minor_version"] == 2
    assert stored["data"]["workouts"][0]["best_km_kmh"] == 4.5
    # Erneut geschickt: unveraendert
    response = await post(hass_client, payload(workout("R", name=RIDE)))
    assert (await response.json())["geaendert"] == 0


async def test_from_0_1_20_adds_speed(
    hass: HomeAssistant, entry, hass_client, hass_storage
):
    await post(hass_client, payload(workout("R", name=RIDE)))

    def as_0_1_20(data, w):
        data["best_km_version"] = 2
        w.pop("best_km_kmh", None)

    stored = await _old_index(hass, entry, hass_storage, as_0_1_20)
    assert entry.runtime_data.store.workouts[0]["best_km_kmh"] == 4.5
    assert "best_km_version" not in stored["data"]


async def test_from_0_1_21_keeps_values(
    hass: HomeAssistant, entry, hass_client, hass_storage
):
    await post(hass_client, payload(workout("R", name=RIDE)))

    def as_0_1_21(data, w):
        data["best_km_version"] = 3
        # Erkennungszeichen: wird nicht neu gerechnet, Details nicht geladen
        w["best_km_s"] = 1.0

    stored = await _old_index(hass, entry, hass_storage, as_0_1_21)
    assert entry.runtime_data.store.workouts[0]["best_km_s"] == 1.0
    assert "best_km_version" not in stored["data"]
    assert stored["minor_version"] == 2


async def test_runs_only_once(hass: HomeAssistant, entry, hass_client, hass_storage):
    await post(hass_client, payload(workout("R", name=RIDE)))
    await _old_index(hass, entry, hass_storage, _as_0_1_19)
    # Nach der Migration: kein zweites Mal beim naechsten Start
    hass_storage[_key(entry)]["data"]["workouts"][0]["best_km_s"] = 1.0
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.store.workouts[0]["best_km_s"] == 1.0


async def test_without_details_value_stays(
    hass: HomeAssistant, entry, hass_client, hass_storage
):
    await post(hass_client, payload(workout()))

    def no_details(data, w):
        _as_0_1_19(data, w)
        w["has_detail"] = False

    # Wie nach der Aufbewahrung: die Detaildatei fehlt wirklich
    for key in [k for k in hass_storage if k.startswith("ha_training.detail.")]:
        del hass_storage[key]

    await _old_index(hass, entry, hass_storage, no_details)
    workout_ = entry.runtime_data.store.workouts[0]
    assert workout_["best_km_s"] == 660
    # km/h als None wie beim Einlesen zu Fuss: erneut geschickt unveraendert
    # (hinter der Aufbewahrung; davor holte das Senden die Details zurueck)
    assert workout_["best_km_kmh"] is None
    await entry.runtime_data.store.async_set_keep_details(0)
    response = await post(hass_client, payload(workout()))
    assert (await response.json())["geaendert"] == 0


async def test_older_code_reads_1_2(hass: HomeAssistant, hass_storage):
    # Zurueck auf 0.1.21: dessen Store (1.1, ohne Migration) laedt 1.2 unveraendert
    data = {"workouts": [{"id": "A", "best_km_s": 37.756}], "deleted": []}
    hass_storage["ha_training.index.X"] = {
        "version": 1,
        "minor_version": 2,
        "key": "ha_training.index.X",
        "data": data,
    }
    assert await Store(hass, 1, "ha_training.index.X").async_load() == data


async def test_unknown_major_version(hass: HomeAssistant):
    store = IndexStore(hass, "ha_training.index.Y", lambda _id: None)
    with pytest.raises(NotImplementedError):
        await store._async_migrate_func(2, 1, {})
