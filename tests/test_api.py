"""WebSocket-API, Ereignis, Wochensummen, Diagnose und Entfernen."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.ha_training.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import CENTER, TZ, WEBHOOK_ID, payload, post, workout


async def test_websocket_list_and_detail(
    hass: HomeAssistant, entry, hass_client, hass_ws_client
):
    later = datetime(2026, 10, 30, 18, 0, tzinfo=TZ)
    await post(hass_client, payload(workout("A"), workout("B", later, minutes=10)))
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ha_training/workouts"})
    msg = await ws.receive_json()
    assert msg["success"]
    # Neuestes zuerst
    assert [w["id"] for w in msg["result"]["workouts"]] == ["B", "A"]

    await ws.send_json({"id": 2, "type": "ha_training/workout", "workout_id": "A"})
    msg = await ws.receive_json()
    assert msg["success"]
    assert msg["result"]["summary"]["id"] == "A"
    detail = msg["result"]["detail"]
    assert detail["route_fields"] == ["t", "lat", "lon", "alt", "speed", "hacc"]
    assert len(detail["route"]) == 1620
    assert detail["pauses"]

    await ws.send_json({"id": 3, "type": "ha_training/workout", "workout_id": "X"})
    msg = await ws.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_websocket_without_entry(hass: HomeAssistant, entry, hass_ws_client):
    await hass.config_entries.async_unload(entry.entry_id)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ha_training/workouts"})
    msg = await ws.receive_json()
    assert msg["error"]["code"] == "not_found"


async def test_event_only_for_recent_workouts(
    hass: HomeAssistant, entry, hass_client, freezer: FrozenDateTimeFactory
):
    freezer.move_to("2026-10-30 16:00:00+01:00")
    old = workout("ALT", datetime(2026, 10, 20, 9, 0, tzinfo=TZ))
    await post(hass_client, payload(old))
    await hass.async_block_till_done()
    assert hass.states.get("event.training_new_workout").state == "unknown"

    await post(hass_client, payload(workout("NEU")))
    await hass.async_block_till_done()
    state = hass.states.get("event.training_new_workout")
    assert state.state != "unknown"
    assert state.attributes["event_type"] == "neues_training"
    assert state.attributes["workout_id"] == "NEU"
    assert state.attributes["distance_km"] == 2.5
    assert "route" not in state.attributes


async def test_week_sums(
    hass: HomeAssistant, entry, hass_client, freezer: FrozenDateTimeFactory
):
    # Donnerstag; Montag derselben Woche ist der 26.10.2026
    freezer.move_to("2026-10-29 20:00:00+01:00")
    this_week = workout("W1", datetime(2026, 10, 27, 8, 0, tzinfo=TZ))
    also = workout("W2", datetime(2026, 10, 29, 8, 0, tzinfo=TZ))
    last_week = workout("W0", datetime(2026, 10, 25, 8, 0, tzinfo=TZ))
    await post(hass_client, payload(this_week, also, last_week))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.training_workouts_this_week").state == "2"
    distance = hass.states.get("sensor.training_distance_this_week")
    assert distance.state == "5.0"
    assert distance.attributes["state_class"] == "total"
    assert dt_util.parse_datetime(distance.attributes["last_reset"]) == datetime(
        2026, 10, 26, 0, 0, tzinfo=dt_util.get_default_time_zone()
    )

    # Neue Woche: Summen fallen auf 0, kurz nach Mitternacht neu berechnet
    freezer.move_to("2026-11-02 00:00:06+01:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("sensor.training_workouts_this_week").state == "0"


async def test_diagnostics_without_secrets_and_route(
    hass: HomeAssistant, entry, hass_client
):
    await post(hass_client, payload(workout()))
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diag)
    assert WEBHOOK_ID not in text
    assert diag["entry"]["data"]["webhook_id"] == "**REDACTED**"
    assert diag["latest"][0]["detail"]["route_points"] == 1620
    assert str(CENTER[0])[:5] not in text
    assert "latitude" not in text and '"route"' not in text


async def test_remove_entry_deletes_storage(hass: HomeAssistant, entry, hass_client):
    await post(hass_client, payload(workout()))
    store = entry.runtime_data.store
    assert await store.async_get_detail("TEST-0001")
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    from custom_components.ha_training.storage import TrainingStore

    fresh = TrainingStore(hass, entry.entry_id, 10)
    await fresh.async_load()
    assert fresh.workouts == []
    assert hass.states.get("sensor.training_latest_workout") is None


async def test_restart_keeps_workouts(hass: HomeAssistant, entry, hass_client):
    await post(hass_client, payload(workout()))
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(entry.runtime_data.store.workouts) == 1
    assert hass.states.get("sensor.training_latest_workout_distance").state == "2.5"


def test_week_start_is_monday():
    from custom_components.ha_training.sensor import week_start

    sunday = datetime(2026, 11, 1, 23, 59, tzinfo=TZ)
    assert week_start(sunday).date() == (sunday - timedelta(days=6)).date()
