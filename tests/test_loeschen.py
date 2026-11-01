"""Loeschen einzelner Trainings (Dienst, WebSocket, Sperrliste) und GPX-Export."""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime
from unittest.mock import patch

import pytest
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers.storage import Store

from custom_components.ha_training.const import DOMAIN
from custom_components.ha_training.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.ha_training.gpx import build_gpx, filename
from custom_components.ha_training.parser import parse_workout
from custom_components.ha_training.storage import TrainingStore

from .conftest import TZ, payload, post, workout

NS = {
    "g": "http://www.topografix.com/GPX/1/1",
    "t": "http://www.garmin.com/xmlschemas/TrackPointExtension/v1",
}
LATER = datetime(2026, 10, 30, 18, 0, tzinfo=TZ)


async def _two(hass_client):
    await post(hass_client, payload(workout("ALT"), workout("NEU", LATER, minutes=5)))


async def _delete(hass, workout_id, **kwargs):
    await hass.services.async_call(
        DOMAIN, "delete_workout", {"workout_id": workout_id}, blocking=True, **kwargs
    )


async def test_delete_latest_updates_sensors(hass: HomeAssistant, entry, hass_client):
    await _two(hass_client)
    store = entry.runtime_data.store
    assert hass.states.get("sensor.training_workouts_this_week").state == "2"
    assert hass.states.get("sensor.training_latest_workout").attributes[
        "workout_id"
    ] == ("NEU")

    await _delete(hass, "NEU")
    await hass.async_block_till_done()

    assert [w["id"] for w in store.workouts] == ["ALT"]
    assert store.deleted == {"NEU"}
    latest = hass.states.get("sensor.training_latest_workout")
    assert latest.attributes["workout_id"] == "ALT"
    assert hass.states.get("sensor.training_workouts_this_week").state == "1"
    # Auch die Detaildatei ist weg, nicht nur der Eintrag im Index
    assert await store._detail_store("NEU").async_load() is None
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["deleted"] == 1


async def test_deleted_workout_is_not_added_again(
    hass: HomeAssistant, entry, hass_client
):
    await _two(hass_client)
    await _delete(hass, "NEU")
    response = await post(
        hass_client, payload(workout("ALT"), workout("NEU", LATER, minutes=5))
    )
    body = await response.json()
    assert body["neu"] == 0
    assert body["geloescht"] == 1
    assert [w["id"] for w in entry.runtime_data.store.workouts] == ["ALT"]


async def test_undelete_lets_it_come_back(hass: HomeAssistant, entry, hass_client):
    await _two(hass_client)
    await _delete(hass, "NEU")
    await hass.services.async_call(
        DOMAIN, "undelete_workout", {"workout_id": "NEU"}, blocking=True
    )
    assert entry.runtime_data.store.deleted == set()
    response = await post(hass_client, payload(workout("NEU", LATER, minutes=5)))
    assert (await response.json())["neu"] == 1


async def test_block_list_survives_restart(hass: HomeAssistant, entry, hass_client):
    await _two(hass_client)
    await _delete(hass, "NEU")
    reloaded = TrainingStore(hass, entry.entry_id, 200)
    await reloaded.async_load()
    assert reloaded.deleted == {"NEU"}
    assert [w["id"] for w in reloaded.workouts] == ["ALT"]


async def test_delete_and_undelete_unknown_id(hass: HomeAssistant, entry):
    with pytest.raises(ServiceValidationError) as err:
        await _delete(hass, "GIBTSNICHT")
    assert err.value.translation_key == "workout_not_found"
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "undelete_workout", {"workout_id": "GIBTSNICHT"}, blocking=True
        )
    assert err.value.translation_key == "workout_not_deleted"


async def test_delete_service_needs_admin(
    hass: HomeAssistant, entry, hass_client, hass_read_only_user
):
    await _two(hass_client)
    with pytest.raises(Unauthorized):
        await _delete(hass, "NEU", context=Context(user_id=hass_read_only_user.id))
    assert len(entry.runtime_data.store.workouts) == 2


async def test_websocket_delete_admin_only(
    hass: HomeAssistant,
    entry,
    hass_client,
    hass_ws_client,
    hass_read_only_access_token,
):
    await _two(hass_client)
    guest = await hass_ws_client(hass, hass_read_only_access_token)
    await guest.send_json(
        {"id": 1, "type": "ha_training/delete_workout", "workout_id": "NEU"}
    )
    msg = await guest.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"
    assert len(entry.runtime_data.store.workouts) == 2

    admin = await hass_ws_client(hass)
    await admin.send_json(
        {"id": 1, "type": "ha_training/delete_workout", "workout_id": "NEU"}
    )
    msg = await admin.receive_json()
    assert msg["success"]
    assert msg["result"] == {"deleted": "NEU"}
    await admin.send_json(
        {"id": 2, "type": "ha_training/delete_workout", "workout_id": "NEU"}
    )
    msg = await admin.receive_json()
    assert msg["error"]["code"] == "not_found"


async def test_delete_while_webhook_runs(hass: HomeAssistant, entry, hass_client):
    # Loeschen und Annahme greifen auf dieselbe Liste zu; mit dem Lock bleibt
    # sie stimmig, egal wer zuerst drankommt
    await _two(hass_client)
    store = entry.runtime_data.store
    parsed = [parse_workout(workout(f"P{i}", minutes=2, pause=None)) for i in range(5)]
    await asyncio.gather(store.async_add(parsed), store.async_delete("ALT"))
    ids = [w["id"] for w in store.workouts]
    assert "ALT" not in ids
    assert sorted(ids) == ["NEU", "P0", "P1", "P2", "P3", "P4"]
    assert len(ids) == len(set(ids))


def test_gpx_has_points_segments_and_heart_rate():
    summary, detail = parse_workout(workout())
    text = build_gpx(summary, detail)
    root = ET.fromstring(text)
    assert root.tag == "{http://www.topografix.com/GPX/1/1}gpx"
    assert root.get("version") == "1.1"
    segments = root.findall("g:trk/g:trkseg", NS)
    # Die Pause von Minute 10 bis 13 trennt zwei Segmente
    assert len(segments) == 2
    points = root.findall(".//g:trkpt", NS)
    assert len(points) == len(detail["route"]) == 1620
    first = points[0]
    assert float(first.get("lat")) == detail["route"][0][1]
    assert first.find("g:time", NS).text == "2026-10-30T14:00:00Z"
    assert first.find("g:ele", NS) is not None
    assert first.find(".//t:hr", NS).text == "100"
    assert root.find("g:metadata/g:name", NS).text == "Outdoor Spaziergang"


def test_gpx_escapes_name_and_needs_route():
    raw = workout(name='Lauf <"&"> Park')
    summary, detail = parse_workout(raw)
    root = ET.fromstring(build_gpx(summary, detail))
    assert root.find("g:trk/g:name", NS).text == 'Lauf <"&"> Park'
    assert filename(summary) == "training-2026-10-30-1500-lauf-park.gpx"
    detail["route"] = []
    assert build_gpx(summary, detail) is None


async def test_websocket_gpx(hass: HomeAssistant, entry, hass_client, hass_ws_client):
    await _two(hass_client)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ha_training/gpx", "workout_id": "ALT"})
    msg = await ws.receive_json()
    assert msg["success"]
    assert msg["result"]["filename"].endswith(".gpx")
    assert ET.fromstring(msg["result"]["gpx"]).findall(".//g:trkpt", NS)
    await ws.send_json({"id": 2, "type": "ha_training/gpx", "workout_id": "X"})
    msg = await ws.receive_json()
    assert msg["error"]["code"] == "not_found"


async def test_delete_during_prune_keeps_list_consistent(
    hass: HomeAssistant, entry, hass_client
):
    # Ohne Lock: Waehrend das Ausduennen auf das Loeschen einer Detaildatei
    # wartet, entfernt async_delete das neueste Training; die Liste rueckt auf
    # und das Ausduennen ueberspringt ein Training, das seine Details behaelt.
    base = datetime(2026, 10, 26, 9, 0, tzinfo=TZ)
    await post(
        hass_client,
        payload(
            *(
                workout(f"W{i}", base.replace(day=26 + i), minutes=3, pause=None)
                for i in range(4)
            )
        ),
    )
    store = entry.runtime_data.store
    assert [w["id"] for w in store.workouts] == ["W3", "W2", "W1", "W0"]
    # Das echte Store.async_remove wartet auf einen Executor-Job und gibt dabei
    # die Kontrolle ab; das Mock der Testumgebung nicht. Hier nachgebildet.
    mocked = Store.async_remove

    async def yielding_remove(self):
        await asyncio.sleep(0)
        await mocked(self)

    with patch.object(Store, "async_remove", yielding_remove):
        await asyncio.gather(store.async_set_keep_details(1), store.async_delete("W3"))
    assert [w["id"] for w in store.workouts] == ["W2", "W1", "W0"]
    assert [w["has_detail"] for w in store.workouts] == [False, False, False]
