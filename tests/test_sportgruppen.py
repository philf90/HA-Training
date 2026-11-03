"""Sportart aus dem Namen: Wochensummen je Gruppe und Darstellung in der Karte."""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from custom_components.ha_training.sport import sport_of

from .conftest import TZ, payload, post, workout
from .test_karte import js


@pytest.mark.parametrize(
    ("name", "sport"),
    [
        # Echte Namen aus der Instanz (31.10. und 03.11.2026)
        ("Outdoor Spaziergang", "foot"),
        ("Outdoor Radfahren", "cycling"),
        # Deutsch und Englisch, Ort davor oder nicht
        ("Indoor Radfahren", "cycling"),
        ("Outdoor Lauf", "foot"),
        ("Laufen", "foot"),
        ("Wandern", "foot"),
        ("Gehen", "foot"),
        ("Outdoor Walk", "foot"),
        ("Outdoor Run", "foot"),
        ("Hiking", "foot"),
        ("Outdoor Cycling", "cycling"),
        ("Hand Cycling", "cycling"),
        ("Mountainbike", "cycling"),
        ("Pool Swim", "swimming"),
        ("Schwimmen im Becken", "swimming"),
        ("Freiwasserschwimmen", "swimming"),
        # Nicht zu Fuss, obwohl "lauf" oder "walk" darin steckt
        ("Skilanglauf", "other"),
        ("Wheelchair Walk Pace", "other"),
        ("Rollstuhl Gehtempo", "other"),
        ("Yoga", "other"),
        ("Funktionelles Krafttraining", "other"),
        ("", "other"),
        (None, "other"),
        (42, "other"),
    ],
)
def test_sport_of(name, sport):
    assert sport_of(name) == sport


def _state(hass: HomeAssistant, entity_id: str) -> float:
    return float(hass.states.get(entity_id).state)


async def test_week_sums_per_sport(
    hass: HomeAssistant, entry, hass_client, freezer: FrozenDateTimeFactory
):
    # Mittwoch; diese Woche ab Mo 02.11., letzte Woche 26.10.-01.11.
    freezer.move_to("2026-11-04 12:00:00+01:00")
    walk = workout("GEHEN", datetime(2026, 11, 2, 9, 0, tzinfo=TZ), minutes=30)
    bike = workout(
        "RAD", datetime(2026, 11, 3, 8, 0, tzinfo=TZ), name="Outdoor Radfahren"
    )
    bike["distance"] = {"qty": 7.611, "units": "km"}
    yoga = workout("YOGA", datetime(2026, 11, 3, 18, 0, tzinfo=TZ), name="Yoga")
    yoga["distance"] = {"qty": 0, "units": "km"}
    old_bike = workout(
        "RAD-ALT", datetime(2026, 10, 31, 10, 0, tzinfo=TZ), name="Outdoor Cycling"
    )
    old_bike["distance"] = {"qty": 20, "units": "km"}
    await post(hass_client, payload(walk, bike, yoga, old_bike))
    await hass.async_block_till_done()

    # Gesamt wie bisher: alle drei dieser Woche, Kilometer gemischt
    assert _state(hass, "sensor.training_workouts_this_week") == 3
    total = _state(hass, "sensor.training_distance_this_week")
    walk_km = _state(hass, "sensor.training_distance_on_foot_this_week")
    assert total == pytest.approx(walk_km + 7.611)

    assert _state(hass, "sensor.training_workouts_on_foot_this_week") == 1
    assert _state(hass, "sensor.training_cycling_workouts_this_week") == 1
    assert _state(hass, "sensor.training_cycling_distance_this_week") == 7.611
    assert _state(hass, "sensor.training_swimming_workouts_this_week") == 0
    assert _state(hass, "sensor.training_swimming_distance_this_week") == 0
    assert _state(hass, "sensor.training_cycling_time_this_week") > 0

    # Letzte Woche: nur das alte Radtraining
    assert _state(hass, "sensor.training_cycling_workouts_last_week") == 1
    assert _state(hass, "sensor.training_cycling_distance_last_week") == 20
    assert _state(hass, "sensor.training_workouts_on_foot_last_week") == 0

    # Statistik: diese Woche als Summe mit Ruecksetzen, letzte Woche ohne
    this_week = hass.states.get("sensor.training_cycling_distance_this_week")
    assert this_week.attributes["state_class"] == "total"
    assert this_week.attributes["unit_of_measurement"] == "km"
    assert "last_reset" in this_week.attributes
    last_week = hass.states.get("sensor.training_cycling_distance_last_week")
    assert "state_class" not in last_week.attributes
    assert "last_reset" not in last_week.attributes


async def test_websocket_adds_sport_without_storing_it(
    hass: HomeAssistant, entry, hass_client, hass_ws_client
):
    bike = workout("RAD", name="Outdoor Radfahren")
    await post(hass_client, payload(workout("GEHEN"), bike))
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ha_training/workouts"})
    listed = (await ws.receive_json())["result"]["workouts"]
    assert {w["id"]: w["sport"] for w in listed} == {"GEHEN": "foot", "RAD": "cycling"}
    await ws.send_json({"id": 2, "type": "ha_training/workout", "workout_id": "RAD"})
    assert (await ws.receive_json())["result"]["summary"]["sport"] == "cycling"
    # Nur berechnet: Index unveraendert, ein erneutes Senden bleibt "unveraendert"
    store = entry.runtime_data.store
    assert all("sport" not in w for w in store.workouts)
    response = await post(hass_client, payload(bike))
    assert (await response.json())["geaendert"] == 0


CARD = r"""
(() => {
  const root = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] };
  const card = new HaTrainingCard();
  card.shadowRoot = { getElementById: (id) => (id === "inhalt" ? root : null) };
  card._config = {};
  card._hass = { language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" }, user: { is_admin: false } };
  card._summary = SUMMARY;
  card._workouts = [card._summary];
  card._current = card._summary.id;
  card._points = [];
  card._detail = { splits: [{ distance_m: 1000, active_s: 240, speed_kmh: 15, hr_avg: 100, hr_max: 110 }] };
  // Tabelle aufgeklappt (seit 0.1.18 standardmaessig zu, siehe test_kilometer.py)
  card._splitsOpen = true;
  card._render();
  return root.innerHTML;
})()
"""

BASE = {
    "id": "A-1",
    "name": "Outdoor Radfahren",
    "start": "2026-11-03T08:11:44+01:00",
    "speed_kmh": 14.31,
    "speed_max_kmh": 102.75,
    "pace_s_per_km": 252,
    "cadence_spm": 10,
    "temperature_c": 3.6,
    "humidity_pct": 84,
}


def _card(**summary) -> str:
    return js(CARD.replace("SUMMARY", json.dumps({**BASE, **summary})))


def test_card_cycling():
    html = _card(sport="cycling")
    assert 'icon="mdi:bike"' in html
    # Keine Schrittfrequenz; dafuer Temperatur mit Luftfeuchte
    assert "Schrittfrequenz" not in html
    assert "Temperatur" in html and "84 % Luftfeuchte" in html
    # Unter dem Tempo der Hoechstwert statt min/km
    assert "max 102,8 km/h" in html
    assert "4:12 min/km" not in html
    # Kilometer-Tabelle: km/h vorne, min/km klein darunter
    row = html[html.index("<tbody>") :]
    assert row.index("15,0 <small>km/h</small>") < row.index("4:00 min/km")


def test_card_foot_unchanged():
    html = _card(name="Outdoor Spaziergang", sport="foot")
    assert 'icon="mdi:walk"' in html
    assert "Schrittfrequenz" in html and "4 °C · 84 % Luftfeuchte" in html
    assert "4:12 min/km" in html
    row = html[html.index("<tbody>") :]
    assert row.index("4:00 <small>min/km</small>") < row.index("15,0 km/h")


@pytest.mark.parametrize(
    ("sport", "icon"),
    [("swimming", "mdi:swim"), ("other", "mdi:heart-pulse"), (None, "mdi:walk")],
)
def test_card_icon(sport, icon):
    summary = {"sport": sport} if sport else {}
    html = _card(**summary)
    assert f'icon="{icon}"' in html
    # Ohne Angabe (aeltere Integration) wie bisher: Schrittfrequenz
    assert ("Schrittfrequenz" in html) is (sport is None)
