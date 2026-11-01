"""Last am Webhook: Parsen im Executor, Obergrenze, Aufbewahrung, Wochensummen."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from custom_components.ha_training import parser, sensor
from custom_components.ha_training.parser import decode_and_parse

from .conftest import payload, post, workout

UTC = timezone.utc


async def test_too_many_workouts_rejected(hass: HomeAssistant, entry, hass_client):
    with patch.object(parser, "MAX_WORKOUTS_PER_CALL", 3):
        many = [workout(f"V{i}", minutes=2, pause=None) for i in range(4)]
        response = await post(hass_client, payload(*many))
        assert response.status == 413
        assert await response.json() == {"fehler": "zu viele Trainings", "maximal": 3}
        assert entry.runtime_data.store.workouts == []
        # Genau an der Grenze geht es
        response = await post(hass_client, payload(*many[:3]))
        assert response.status == 200
        assert (await response.json())["neu"] == 3


async def test_decoding_runs_outside_event_loop(
    hass: HomeAssistant, entry, hass_client
):
    threads = []

    def spy(body):
        threads.append(threading.current_thread() is threading.main_thread())
        return decode_and_parse(body)

    with patch("custom_components.ha_training.decode_and_parse", spy):
        response = await post(hass_client, payload(workout()))
    assert (await response.json())["neu"] == 1
    # Aufgerufen, aber nicht im Thread des Event-Loops
    assert threads == [False]


async def test_empty_body_is_bad_request(hass: HomeAssistant, entry, hass_client):
    response = await post(hass_client, b"", raw=True)
    assert response.status == 400
    assert await response.json() == {"fehler": "kein JSON"}


async def test_no_detail_files_beyond_retention(
    hass: HomeAssistant, entry, hass_client
):
    store = entry.runtime_data.store
    await store.async_set_keep_details(2)
    base = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    four = [
        workout(f"A{i}", start=base + timedelta(days=i), minutes=2, pause=None)
        for i in range(4)
    ]
    saved = []
    original = Store.async_save

    async def counting_save(self, data):
        saved.append(self.key)
        await original(self, data)

    with patch.object(Store, "async_save", counting_save):
        response = await post(hass_client, payload(*four))
    assert (await response.json())["neu"] == 4
    details = sorted(k.rsplit(".", 1)[-1] for k in saved if ".detail." in k)
    # Nur die beiden neuesten; die aelteren wurden nie geschrieben
    assert details == ["A2", "A3"]
    assert [w["has_detail"] for w in store.workouts] == [True, True, False, False]


async def test_same_id_twice_in_one_call(hass: HomeAssistant, entry, hass_client):
    response = await post(hass_client, payload(workout(), workout()))
    body = await response.json()
    assert body["neu"] == 1
    assert body["geaendert"] == 0
    assert len(entry.runtime_data.store.workouts) == 1


def test_store_serializes_outside_event_loop(hass: HomeAssistant):
    from custom_components.ha_training.storage import TrainingStore

    store = TrainingStore(hass, "e", 10)
    assert store._index._serialize_in_event_loop is False
    assert store._detail_store("X")._serialize_in_event_loop is False


class _Store:
    def __init__(self, workouts):
        self.workouts = workouts


def test_week_stops_after_older_workouts():
    now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    # Neuestes zuerst: 3 in dieser Woche, dann 1000 aeltere im Abstand von 6 h
    starts = [now - timedelta(hours=h) for h in (1, 30, 60)] + [
        datetime(2026, 10, 25, 12, 0, tzinfo=UTC) - timedelta(hours=6 * i)
        for i in range(1000)
    ]
    store = _Store([{"start": s.isoformat()} for s in starts])
    calls = []
    real = sensor.parse_time

    def counting(value):
        calls.append(value)
        return real(value)

    with patch.object(sensor, "parse_time", counting):
        week = sensor.week_workouts(store, now)
    assert len(week) == 3
    # Abbruch nach gut zwei Tagen aelterer Trainings statt 1003 Aufrufen
    assert len(calls) < 20


def test_week_tolerates_text_order_across_offsets():
    # Als Text steht X vor Y, in Wirklichkeit liegt Y nach X: X ist vor der
    # Woche, Y in der Woche. Die Schleife darf an X nicht abbrechen.
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    x = "2026-10-26T01:00:00+14:00"  # 25.10. 11:00 UTC
    y = "2026-10-26T00:30:00-10:00"  # 26.10. 10:30 UTC
    store = _Store([{"start": x}, {"start": y}])
    assert [w["start"] for w in sensor.week_workouts(store, now)] == [y]


async def test_week_sensor_after_many_old_workouts(
    hass: HomeAssistant, entry, hass_client, freezer: FrozenDateTimeFactory
):
    freezer.move_to("2026-10-31 12:00:00+01:00")
    old = [
        workout(
            f"O{i}",
            start=datetime(2026, 9, 1, 9, 0, tzinfo=UTC) + timedelta(hours=i),
            minutes=1,
            pause=None,
        )
        for i in range(40)
    ]
    recent = workout(
        "JETZT", datetime(2026, 10, 30, 9, 0, tzinfo=UTC), minutes=1, pause=None
    )
    await post(hass_client, payload(*old, recent))
    await hass.async_block_till_done()
    count = hass.states.get("sensor.training_workouts_this_week")
    # Nur das Training dieser Woche zaehlt (Woche ab Mo 26.10.)
    assert count.state == "1"


async def test_same_id_twice_last_version_wins(hass: HomeAssistant, entry, hass_client):
    first, second = workout(), workout()
    second["distance"] = {"qty": 2.7, "units": "km"}
    response = await post(hass_client, payload(first, second))
    body = await response.json()
    assert (body["neu"], body["geaendert"]) == (1, 0)
    stored = entry.runtime_data.store.workouts
    assert len(stored) == 1
    assert stored[0]["distance_km"] == 2.7
    assert stored[0]["has_detail"] is True
