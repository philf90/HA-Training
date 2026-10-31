"""Webhook: Annahme, Doppelte, Aenderungen, fehlerhafte Aufrufe."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.ha_training.const import DOMAIN

from .conftest import payload, post, workout


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
