"""Bestleistungen und Serien (E4): Berechnung, Sensoren, Ereignis, Nachtrag."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant

from custom_components.ha_training import rekorde
from custom_components.ha_training.parser import best_km, parse_workout
from custom_components.ha_training.sensor import pace_text

from .conftest import TZ, payload, post, workout


def _split(distance_m, active_s):
    return {"distance_m": distance_m, "active_s": active_s}


def test_best_km_only_full_kilometres():
    splits = [_split(1000, 600), _split(980, 588), _split(1500, 700), _split(400, 100)]
    # 980 m in 588 s = 600 s/km; 1500 m und 400 m zaehlen nicht
    assert best_km(splits) == 600
    assert best_km([_split(1000, 540), _split(1000, 600)]) == 540
    assert best_km([_split(400, 100)]) is None
    assert best_km([_split(None, 300), {"active_s": 300}, "x"]) is None
    assert best_km([_split(1000, 0)]) is None


def test_parser_stores_best_km():
    summary, _ = parse_workout(workout())
    # Testtraining: erster Kilometer 660 s, danach 1,5 km am Stueck
    assert summary["best_km_s"] == 660


def _w(wid, day, name="Outdoor Spaziergang", **values):
    return {
        "id": wid,
        "name": name,
        "start": datetime(2026, 10, day, 9, 0, tzinfo=TZ).isoformat(),
        **values,
    }


def test_records_per_sport():
    workouts = [
        _w("G1", 20, distance_km=3.0, best_km_s=600, elevation_up_m=10),
        _w("G2", 21, distance_km=5.0, best_km_s=640, elevation_up_m=40),
        _w("R1", 22, "Outdoor Radfahren", distance_km=30.0, best_km_s=120),
        _w("Y1", 23, "Yoga", distance_km=99.0),
        _w("S1", 24, "Schwimmen im Becken", distance_km=1.5),
    ]
    r = rekorde.compute(workouts, date(2026, 10, 24))
    assert r["distance_foot"]["workout_id"] == "G2"
    assert r["distance_foot"]["value"] == 5.0
    assert r["best_km_foot"]["workout_id"] == "G1"
    assert r["elevation_foot"]["value"] == 40
    assert r["distance_cycling"]["value"] == 30.0
    assert r["best_km_cycling"]["value"] == 120
    # Kein Wert: keine Bestleistung
    assert r["elevation_cycling"] is None
    assert r["distance_swimming"]["value"] == 1.5
    # Yoga zaehlt bei keiner Sportart, aber fuer die Serie
    assert r[rekorde.STREAK] == 5


@pytest.mark.parametrize("order", [("FRUEH", "SPAET"), ("SPAET", "FRUEH")])
def test_tie_keeps_earlier_workout(order):
    days = {"FRUEH": 20, "SPAET": 22}
    workouts = [_w(wid, days[wid], distance_km=5.0) for wid in order]
    r = rekorde.compute(workouts, date(2026, 10, 24))
    assert r["distance_foot"]["workout_id"] == "FRUEH"


@pytest.mark.parametrize(
    ("days", "today", "current", "longest"),
    [
        ([1, 2, 3, 5, 6], 6, 2, 3),
        # Gestern trainiert, heute noch nicht: Serie laeuft weiter
        ([4, 5], 6, 2, 2),
        # Vorgestern zuletzt: Serie vorbei
        ([3, 4], 6, 0, 2),
        ([], 6, 0, 0),
    ],
)
def test_streaks(days, today, current, longest):
    workouts = [_w(f"W{d}", d) for d in days]
    r = rekorde.compute(workouts, date(2026, 10, today))
    assert (r[rekorde.STREAK], r[rekorde.STREAK_LONGEST]) == (current, longest)


async def test_streak_uses_local_date(hass: HomeAssistant):
    await hass.config.async_set_time_zone("Europe/Berlin")
    # 23:30 UTC am 1.11. ist in Berlin schon der 2.11.
    workouts = [
        {"id": "A", "name": "x", "start": "2026-11-01T09:00:00+01:00"},
        {"id": "B", "name": "x", "start": "2026-11-01T23:30:00+00:00"},
    ]
    assert rekorde.compute(workouts, date(2026, 11, 2))[rekorde.STREAK] == 2


def test_improved_only_with_previous_record():
    before = rekorde.compute([_w("A", 20, distance_km=3.0)], date(2026, 10, 24))
    after = rekorde.compute(
        [_w("A", 20, distance_km=3.0), _w("B", 21, distance_km=4.0)], date(2026, 10, 24)
    )
    events = rekorde.improved(before, after, {"B"})
    keys = {e["record"] for e in events}
    assert "distance_foot" in keys
    record = next(e for e in events if e["record"] == "distance_foot")
    assert (record["value"], record["previous"], record["workout_id"]) == (
        4.0,
        3.0,
        "B",
    )
    # Erstes Training einer Sportart: keine Bestleistung
    empty = rekorde.compute([], date(2026, 10, 24))
    first = rekorde.compute([_w("A", 20, distance_km=3.0)], date(2026, 10, 24))
    assert rekorde.improved(empty, first, {"A"}) == []


def test_pace_text():
    assert pace_text(581) == "9:41 min/km"
    assert pace_text(60) == "1:00 min/km"
    assert pace_text(None) is None


def _state(hass, entity_id):
    return hass.states.get(entity_id)


async def test_record_sensors(
    hass: HomeAssistant, entry, hass_client, freezer: FrozenDateTimeFactory
):
    freezer.move_to("2026-10-31 12:00:00+01:00")
    walk = workout("GEHEN", datetime(2026, 10, 30, 15, 0, tzinfo=TZ))
    bike = workout(
        "RAD", datetime(2026, 10, 31, 8, 0, tzinfo=TZ), name="Outdoor Radfahren"
    )
    bike["distance"] = {"qty": 20.0, "units": "km"}
    await post(hass_client, payload(walk, bike))
    await hass.async_block_till_done()

    longest = _state(hass, "sensor.training_longest_distance_on_foot")
    assert float(longest.state) == 2.5
    assert longest.attributes["workout_id"] == "GEHEN"
    fastest = _state(hass, "sensor.training_fastest_kilometre_on_foot")
    assert float(fastest.state) == 660
    assert fastest.attributes["tempo"] == "11:00 min/km"
    assert fastest.attributes["unit_of_measurement"] == "s"
    assert float(_state(hass, "sensor.training_longest_cycling_distance").state) == 20
    assert _state(hass, "sensor.training_longest_swimming_distance").state == "unknown"
    assert _state(hass, "sensor.training_workout_streak").state == "2"
    assert _state(hass, "sensor.training_longest_workout_streak").state == "2"

    # Zwei Tage ohne Training: Serie vorbei, laengste bleibt
    freezer.move_to("2026-11-02 00:00:06+01:00")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _state(hass, "sensor.training_workout_streak").state == "0"
    assert _state(hass, "sensor.training_longest_workout_streak").state == "2"


async def test_delete_gives_record_to_next_best(
    hass: HomeAssistant, entry, hass_client, freezer: FrozenDateTimeFactory
):
    freezer.move_to("2026-10-31 12:00:00+01:00")
    short = workout("KURZ", datetime(2026, 10, 29, 9, 0, tzinfo=TZ))
    long = workout("LANG", datetime(2026, 10, 30, 9, 0, tzinfo=TZ))
    long["distance"] = {"qty": 6.0, "units": "km"}
    await post(hass_client, payload(short, long))
    await hass.services.async_call(
        "ha_training", "delete_workout", {"workout_id": "LANG"}, blocking=True
    )
    await hass.async_block_till_done()
    sensor = _state(hass, "sensor.training_longest_distance_on_foot")
    assert float(sensor.state) == 2.5
    assert sensor.attributes["workout_id"] == "KURZ"


async def test_new_record_event(
    hass: HomeAssistant, entry, hass_client, freezer: FrozenDateTimeFactory
):
    freezer.move_to("2026-10-31 12:00:00+01:00")
    event_id = "event.training_new_personal_best"
    # Erstes Training: keine Bestleistung
    await post(
        hass_client, payload(workout("A", datetime(2026, 10, 31, 9, 0, tzinfo=TZ)))
    )
    await hass.async_block_till_done()
    assert _state(hass, event_id).state == "unknown"

    # Weiter als vorher: Bestleistung
    longer = workout("B", datetime(2026, 10, 31, 10, 0, tzinfo=TZ))
    longer["distance"] = {"qty": 4.0, "units": "km"}
    await post(hass_client, payload(longer))
    await hass.async_block_till_done()
    state = _state(hass, event_id)
    assert state.attributes["event_type"] == "neue_bestleistung"
    assert state.attributes["record"] == "distance_foot"
    assert state.attributes["value"] == 4.0
    assert state.attributes["previous"] == 2.5
    assert state.attributes["unit"] == "km"
    assert state.attributes["workout_id"] == "B"


async def test_no_record_event_for_old_workouts(
    hass: HomeAssistant, entry, hass_client, freezer: FrozenDateTimeFactory
):
    freezer.move_to("2026-10-31 12:00:00+01:00")
    await post(
        hass_client, payload(workout("A", datetime(2026, 10, 20, 9, 0, tzinfo=TZ)))
    )
    # Laenger, aber eine Woche alt (erster Abgleich): kein Ereignis
    old = workout("B", datetime(2026, 10, 24, 9, 0, tzinfo=TZ))
    old["distance"] = {"qty": 9.0, "units": "km"}
    await post(hass_client, payload(old))
    await hass.async_block_till_done()
    assert _state(hass, "event.training_new_personal_best").state == "unknown"
    # Der Sensor kennt die Bestleistung trotzdem
    longest = _state(hass, "sensor.training_longest_distance_on_foot")
    assert float(longest.state) == 9.0


async def test_backfill_best_km(hass: HomeAssistant, entry, hass_client):
    store = entry.runtime_data.store
    await post(hass_client, payload(workout()))
    # Wie unter 0.1.14 gespeichert: ohne best_km_s
    del store.workouts[0]["best_km_s"]
    revision = store.revision
    assert await store.async_backfill_best_km() == 1
    assert store.workouts[0]["best_km_s"] == 660
    assert store.revision == revision + 1
    # Zweiter Lauf: nichts mehr zu tun
    assert await store.async_backfill_best_km() == 0
    # Erneut geschickt: gilt als unveraendert
    response = await post(hass_client, payload(workout()))
    assert (await response.json())["geaendert"] == 0


async def test_backfill_skips_workouts_without_detail(
    hass: HomeAssistant, entry, hass_client
):
    store = entry.runtime_data.store
    await post(hass_client, payload(workout()))
    del store.workouts[0]["best_km_s"]
    store.workouts[0]["has_detail"] = False
    assert await store.async_backfill_best_km() == 0
    assert "best_km_s" not in store.workouts[0]


async def test_backfill_runs_after_start(hass: HomeAssistant, entry, hass_client):
    store = entry.runtime_data.store
    await post(hass_client, payload(workout()))
    del store.workouts[0]["best_km_s"]
    await store._async_save_index()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.store.workouts[0]["best_km_s"] == 660


def test_record_keys_have_units():
    from custom_components.ha_training.event import RECORD_UNITS

    for key in [*rekorde.RECORDS, rekorde.STREAK_LONGEST]:
        assert any(key.startswith(prefix) for prefix in RECORD_UNITS), key


def test_max_age_unchanged():
    assert timedelta(hours=24) == rekorde.MAX_AGE


async def test_statistics_skipped_without_recorder(hass: HomeAssistant, entry):
    # In diesen Tests laeuft kein Recorder: kein Fehler, nur nichts geschrieben
    from custom_components.ha_training import statistik

    assert "recorder" not in hass.config.components
    assert await statistik.async_rebuild(hass, entry.runtime_data.store) is False


async def test_websocket_records(
    hass: HomeAssistant,
    entry,
    hass_client,
    hass_ws_client,
    hass_read_only_access_token,
):
    # Ohne eingefrorene Zeit: sonst laege das Token des Kontos in der Zukunft
    await post(
        hass_client, payload(workout("G", datetime(2026, 10, 30, 9, 0, tzinfo=TZ)))
    )
    # Auch Konten ohne Adminrechte und ohne Freigabe der Routen: nur Werte
    ws = await hass_ws_client(hass, hass_read_only_access_token)
    await ws.send_json({"id": 1, "type": "ha_training/records"})
    msg = await ws.receive_json()
    assert msg["success"]
    result = msg["result"]
    assert result["distance_foot"]["workout_id"] == "G"
    assert result["best_km_foot"]["value"] == 660
    assert result["distance_cycling"] is None
    assert result["streak_longest"] == 1
    # Keine Koordinaten oder Details
    assert set(result["distance_foot"]) == {"value", "workout_id", "name", "start"}


CARD_RECORDS = r"""
(() => {
  const root = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] };
  const card = new HaTrainingCard();
  card.shadowRoot = { getElementById: (id) => (id === "inhalt" ? root : null) };
  card._config = CONFIG;
  card._hass = { language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" }, user: { is_admin: false } };
  card._summary = { id: "G", name: "Outdoor Spaziergang", start: "2026-10-31T15:30:04+01:00", sport: "foot" };
  card._workouts = [card._summary];
  card._current = "G";
  card._points = [];
  card._detail = null;
  card._records = RECORDS;
  card._render();
  return root.innerHTML;
})()
"""

RECORDS = {
    "distance_foot": {
        "value": 2.913,
        "workout_id": "G",
        "name": "x",
        "start": "2026-10-31T15:30:04+01:00",
    },
    "best_km_foot": {
        "value": 1243,
        "workout_id": "G",
        "name": "x",
        "start": "2026-10-31T15:30:04+01:00",
    },
    "elevation_foot": None,
    "distance_cycling": {
        "value": 7.611,
        "workout_id": "R",
        "name": "y",
        "start": "2026-11-03T08:11:44+01:00",
    },
    "best_km_cycling": {
        "value": 120,
        "workout_id": "R",
        "name": "y",
        "start": "2026-11-03T08:11:44+01:00",
    },
    "elevation_cycling": None,
    "distance_swimming": None,
    "streak": 1,
    "streak_longest": 3,
}


def _card_html(records=RECORDS, config=None):
    import json

    from .test_karte import js

    return js(
        CARD_RECORDS.replace("RECORDS", json.dumps(records)).replace(
            "CONFIG", json.dumps(config or {})
        )
    )


def test_card_records_section():
    html = _card_html()
    assert "Bestleistungen" in html
    section = html[html.index("Bestleistungen") :]
    assert "Längste Distanz zu Fuß</td><td>2,91 <small>km</small>" in section
    assert "Schnellster Kilometer zu Fuß</td><td>20:43 <small>min/km</small>" in section
    # Rad: km/h vorne, min/km darunter (120 s/km = 30 km/h)
    assert "30,0 <small>km/h</small><br><small>2:00 min/km</small>" in section
    # Ohne Wert keine Zeile
    assert "Höhenmeter" not in section and "Schwimmen" not in section
    # Datum als Verweis auf das Training; das gezeigte ist markiert
    assert 'data-w="R"' in section and 'data-w="G"' in section
    assert section.count('aria-current="true"') == 2  # beide Zeilen von G
    assert "31.10.2026" in section and "03.11.2026" in section
    # Serie mit Einzahl und Mehrzahl
    assert "1 Tag</td>" in section and "längste 3 Tage" in section


def test_card_records_hidden():
    # Ohne Daten (aeltere Integration oder records: false) kein Abschnitt
    assert "Bestleistungen" not in _card_html(records=None)
    empty = dict.fromkeys(RECORDS)
    empty.update(streak=0, streak_longest=0)
    assert "Bestleistungen" not in _card_html(records=empty)


def test_card_does_not_fetch_records_when_disabled():
    from .test_karte import js

    got = js(
        r"""
(async () => {
  const calls = [];
  const card = new HaTrainingCard();
  card.shadowRoot = { getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] };
  card._config = CONFIG;
  card._render = () => {};
  card._hass = { callWS: async (req) => { calls.push(req.type); return req.type === "ha_training/workouts" ? { workouts: [] } : {}; } };
  await card._loadList();
  return calls;
})()
""".replace("CONFIG", '{"records": false}')
    )
    assert "ha_training/records" not in got


def test_card_click_on_record_loads_workout():
    from .test_karte import js

    got = js(
        r"""
(async () => {
  const buttons = [];
  const root = {
    innerHTML: "",
    querySelector: () => null,
    querySelectorAll: (sel) => (sel === "[data-w]" ? [{ dataset: { w: "R" }, addEventListener: (_, fn) => buttons.push(fn) }] : []),
  };
  const calls = [];
  const card = new HaTrainingCard();
  card.shadowRoot = { getElementById: (id) => (id === "inhalt" ? root : null) };
  card._config = {};
  card._hass = { language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" }, user: { is_admin: false },
    callWS: async (req) => { calls.push(req); return { summary: { id: req.workout_id, name: "y", start: "2026-11-03T08:11:44+01:00" }, detail: null }; } };
  card._summary = { id: "G", name: "x", start: "2026-10-31T15:30:04+01:00" };
  card._workouts = [card._summary];
  card._current = "G";
  card._points = [];
  card._detail = null;
  card._records = null;
  card._render();
  card._render = () => {};
  buttons[0]();
  await new Promise((r) => setTimeout(r, 0));
  return { selected: card._selected, current: card._current, calls: calls.map((c) => [c.type, c.workout_id]) };
})()
"""
    )
    assert got["selected"] == "R"
    assert got["current"] == "R"
    assert got["calls"] == [["ha_training/workout", "R"]]
