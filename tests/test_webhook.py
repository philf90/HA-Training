"""Webhook: Annahme, Doppelte, Aenderungen, fehlerhafte Aufrufe."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from custom_components.ha_training.const import DOMAIN

from .conftest import TZ, payload, post, workout


async def test_new_workout_creates_sensors(hass: HomeAssistant, entry, hass_client):
    response = await post(hass_client, payload(workout()))
    assert response.status == 200
    assert await response.json() == {
        "trainings": 1,
        "neu": 1,
        "geaendert": 0,
        "verworfen": 0,
    }
    await hass.async_block_till_done()
    assert hass.states.get("sensor.training_latest_workout_distance").state == "2.5"
    assert hass.states.get("sensor.training_latest_workout_duration").state == "27.0"
    assert (
        hass.states.get("sensor.training_latest_workout_active_energy").state == "100.0"
    )
    start = hass.states.get("sensor.training_latest_workout")
    assert start.state == "2026-10-30T14:00:00+00:00"
    assert start.attributes["workout_id"] == "TEST-0001"
    assert start.attributes["name"] == "Outdoor Spaziergang"


async def test_duplicate_is_ignored(hass: HomeAssistant, entry, hass_client):
    await post(hass_client, payload(workout()))
    response = await post(hass_client, payload(workout()))
    assert (await response.json())["neu"] == 0
    assert (await response.json())["geaendert"] == 0
    assert len(entry.runtime_data.store.workouts) == 1


async def test_changed_workout_replaces_old(hass: HomeAssistant, entry, hass_client):
    await post(hass_client, payload(workout()))
    changed = workout()
    changed["distance"] = {"qty": 2.6, "units": "km"}
    response = await post(hass_client, payload(changed))
    assert (await response.json())["geaendert"] == 1
    await hass.async_block_till_done()
    assert hass.states.get("sensor.training_latest_workout_distance").state == "2.6"


async def test_invalid_json(hass: HomeAssistant, entry, hass_client):
    response = await post(hass_client, b"kein json", raw=True)
    assert response.status == 400


async def test_payload_without_workouts(hass: HomeAssistant, entry, hass_client):
    response = await post(hass_client, {"data": {"metrics": []}})
    assert response.status == 200
    assert (await response.json())["trainings"] == 0


async def test_workout_without_id_is_rejected(hass: HomeAssistant, entry, hass_client):
    broken = workout()
    del broken["id"]
    response = await post(hass_client, payload(broken, workout("TEST-0002")))
    body = await response.json()
    assert body["verworfen"] == 1
    assert body["neu"] == 1


async def test_get_is_not_allowed(hass: HomeAssistant, entry, hass_client):
    client = await hass_client()
    response = await client.get("/api/webhook/test-webhook-geheim")
    assert response.status == 405


async def test_unload_removes_webhook(hass: HomeAssistant, entry, hass_client):
    assert await hass.config_entries.async_unload(entry.entry_id)
    response = await post(hass_client, payload(workout()))
    # Unbekannte Webhooks beantwortet Home Assistant mit 200, legt aber nichts an
    assert response.status == 200
    assert hass.states.get("sensor.training_latest_workout").state == "unavailable"
    assert DOMAIN in hass.config.components


async def test_bad_field_types_do_not_drop_batch(
    hass: HomeAssistant, entry, hass_client
):
    broken = workout("TEST-0002")
    broken["activities"] = 5
    broken["splits"] = [{"targetDistance": {"units": "km", "qty": 1}, "items": 5}]
    response = await post(hass_client, payload(workout(), broken))
    assert response.status == 200
    assert await response.json() == {
        "trainings": 2,
        "neu": 2,
        "geaendert": 0,
        "verworfen": 0,
    }
    assert len(entry.runtime_data.store.workouts) == 2


async def test_unsafe_id_is_not_stored(hass: HomeAssistant, entry, hass_client):
    evil = workout('x"><img src=x onerror="alert(1)">')
    response = await post(hass_client, payload(evil, workout("TEST-0002")))
    body = await response.json()
    assert body["verworfen"] == 1
    assert body["neu"] == 1
    assert [w["id"] for w in entry.runtime_data.store.workouts] == ["TEST-0002"]


def _three_days():
    base = datetime(2026, 10, 27, 8, 0, tzinfo=TZ)
    return [
        workout(f"TAG-{i}", start=base + timedelta(days=i), minutes=5, pause=None)
        for i in range(3)
    ]


async def test_resend_beyond_retention_is_unchanged(
    hass: HomeAssistant, entry, hass_client
):
    store = entry.runtime_data.store
    await store.async_set_keep_details(1)
    await post(hass_client, payload(*_three_days()))
    saved = []
    original = Store.async_save

    async def counting_save(self, data):
        saved.append(self.key)
        await original(self, data)

    with patch.object(Store, "async_save", counting_save):
        response = await post(hass_client, payload(*_three_days()))
    assert (await response.json())["geaendert"] == 0
    assert saved == []
    assert [w["has_detail"] for w in store.workouts] == [True, False, False]


async def test_resend_restores_details_within_retention(
    hass: HomeAssistant, entry, hass_client
):
    store = entry.runtime_data.store
    await store.async_set_keep_details(1)
    await post(hass_client, payload(*_three_days()))
    await store.async_set_keep_details(3)
    response = await post(hass_client, payload(*_three_days()))
    assert (await response.json())["geaendert"] == 2
    assert [w["has_detail"] for w in store.workouts] == [True, True, True]
    assert (await store.async_get_detail("TAG-0"))["route"]


async def test_changed_workout_beyond_retention_keeps_no_detail(
    hass: HomeAssistant, entry, hass_client
):
    store = entry.runtime_data.store
    await store.async_set_keep_details(1)
    await post(hass_client, payload(*_three_days()))
    changed = _three_days()
    changed[0]["distance"] = {"qty": 0.4, "units": "km"}
    saved = []
    original = Store.async_save

    async def counting_save(self, data):
        saved.append(self.key)
        await original(self, data)

    with patch.object(Store, "async_save", counting_save):
        response = await post(hass_client, payload(*changed))
    assert (await response.json())["geaendert"] == 1
    # Nur der Index; eine Detaildatei ohne has_detail wuerde nie geloescht
    assert saved == [f"ha_training.index.{entry.entry_id}"]
    oldest = store.get("TAG-0")
    assert oldest["distance_km"] == 0.4
    assert oldest["has_detail"] is False
