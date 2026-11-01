"""Letzte Woche (Nachzuegler) und Zaehler "revision" fuer die Karte."""

from __future__ import annotations

from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from custom_components.ha_training import sensor

from .conftest import TZ, payload, post, workout


def _state(hass, key):
    return hass.states.get(f"sensor.training_{key}").state


async def test_late_sunday_workout_counts_in_last_week(
    hass: HomeAssistant, entry, hass_client, freezer: FrozenDateTimeFactory
):
    # Montag 02.11. 08:00; das Training lief Sonntag 01.11. 22:00-22:30 und
    # kommt erst jetzt an
    freezer.move_to("2026-11-02 08:00:00+01:00")
    sunday = datetime(2026, 11, 1, 22, 0, tzinfo=TZ)
    await post(hass_client, payload(workout("SONNTAG", sunday)))
    await hass.async_block_till_done()
    assert _state(hass, "workouts_this_week") == "0"
    assert _state(hass, "workouts_last_week") == "1"
    assert _state(hass, "distance_last_week") == "2.5"
    assert _state(hass, "workout_time_last_week") == "27.0"
    assert _state(hass, "active_energy_last_week") == "100.0"
    last = hass.states.get("sensor.training_distance_last_week")
    assert "state_class" not in last.attributes
    assert "last_reset" not in last.attributes


async def test_week_boundaries(hass: HomeAssistant, entry, hass_client, freezer):
    freezer.move_to("2026-11-04 12:00:00+01:00")  # Mittwoch
    starts = {
        "VORVORWOCHE": datetime(2026, 10, 25, 23, 59, tzinfo=TZ),
        "VORWOCHE_ANFANG": datetime(2026, 10, 26, 0, 0, tzinfo=TZ),
        "VORWOCHE_ENDE": datetime(2026, 11, 1, 23, 59, tzinfo=TZ),
        "DIESE_WOCHE": datetime(2026, 11, 2, 0, 0, tzinfo=TZ),
    }
    await post(
        hass_client,
        payload(*(workout(k, v, minutes=5, pause=None) for k, v in starts.items())),
    )
    await hass.async_block_till_done()
    assert _state(hass, "workouts_last_week") == "2"
    assert _state(hass, "workouts_this_week") == "1"


def test_previous_week_start_across_dst():
    # Woche mit Umstellung auf Winterzeit (So 25.10.2026): Montag 00:00 bleibt
    # Montag 00:00 Ortszeit, auch wenn die Woche 169 Stunden hat
    from homeassistant.util import dt as dt_util

    dt_util.set_default_time_zone(dt_util.get_time_zone("Europe/Berlin"))
    now = datetime(2026, 10, 28, 12, 0, tzinfo=TZ)
    begin = sensor.previous_week_start(now)
    assert begin.isoformat() == "2026-10-19T00:00:00+02:00"
    # Ueber Zeitstempel: Python rechnet bei gleichem tzinfo in Wandzeit (7 Tage)
    elapsed = sensor.week_start(now).timestamp() - begin.timestamp()
    assert elapsed == timedelta(hours=169).total_seconds()


async def test_revision_changes_on_every_visible_change(
    hass: HomeAssistant, entry, hass_client
):
    def revision():
        return hass.states.get("sensor.training_latest_workout").attributes["revision"]

    await post(hass_client, payload(workout()))
    await hass.async_block_till_done()
    first = revision()

    # Gleiches Training noch einmal: nichts geaendert, kein neuer Zaehler
    await post(hass_client, payload(workout()))
    await hass.async_block_till_done()
    assert revision() == first

    # Dasselbe Training geaendert: workout_id bleibt, Zaehler steigt (F5)
    changed = workout()
    changed["distance"] = {"qty": 2.7, "units": "km"}
    await post(hass_client, payload(changed))
    await hass.async_block_till_done()
    latest = hass.states.get("sensor.training_latest_workout")
    assert latest.attributes["workout_id"] == "TEST-0001"
    assert revision() == first + 1

    # Optionen geaendert (z. B. Freigabe der Routen): Zaehler steigt
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"keep_details": 200, "require_token": False}
    )
    await hass.async_block_till_done()
    assert revision() == first + 2


def test_revision_is_not_recorded():
    assert "revision" in sensor.TrainingSensor._unrecorded_attributes


async def test_revision_changes_when_older_workout_is_deleted(
    hass: HomeAssistant, entry, hass_client
):
    older = workout(
        "ALT", datetime(2026, 10, 20, 9, 0, tzinfo=TZ), minutes=5, pause=None
    )
    await post(hass_client, payload(workout(), older))
    await hass.async_block_till_done()
    latest = hass.states.get("sensor.training_latest_workout")
    before = latest.attributes["revision"]
    await hass.services.async_call(
        "ha_training", "delete_workout", {"workout_id": "ALT"}, blocking=True
    )
    await hass.async_block_till_done()
    latest = hass.states.get("sensor.training_latest_workout")
    # Das neueste Training bleibt dasselbe, die Karte muss trotzdem neu laden
    assert latest.attributes["workout_id"] == "TEST-0001"
    assert latest.attributes["revision"] == before + 1
