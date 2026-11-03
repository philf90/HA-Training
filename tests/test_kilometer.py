"""0.1.18: Kilometer als Balken mit aufklappbarer Tabelle (Variante C),
Verlauf in einer Unterkarte, Filter nach Sportart (E2), visueller Editor (V5)."""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from homeassistant.core import HomeAssistant

from .conftest import TZ, payload, post, workout
from .test_karte import js
from .test_rekorde import _records_card

CARD = r"""
(() => {
  const handlers = {};
  const button = { attrs: {}, textContent: "", addEventListener: (_, fn) => { handlers.tabelle = fn; }, setAttribute(k, v) { this.attrs[k] = v; } };
  const place = { innerHTML: "" };
  let renders = 0;
  const root = {
    innerHTML: "",
    querySelector: (sel) => (sel === '[data-a="tabelle"]' ? button : sel === ".tabelle-platz" ? place : null),
    querySelectorAll: (sel) => (sel === "[data-km]" ? BARS.map((i) => ({ dataset: { km: String(i) }, addEventListener: (_, fn) => { handlers["km" + i] = fn; }, setAttribute() {} })) : []),
  };
  const card = new HaTrainingCard();
  card.shadowRoot = { getElementById: (id) => (id === "inhalt" ? root : null), querySelectorAll: () => [] };
  card._config = {};
  card._hass = { language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" }, user: { is_admin: false } };
  card._summary = SUMMARY;
  card._workouts = [card._summary];
  card._current = card._summary.id;
  card._points = [];
  card._detail = { heart_rate: [[1, 100, 100, 100]], splits: SPLITS };
  card._color = () => "#000000";  // kein getComputedStyle in Node
  card._initCharts = () => {};
  const shown = [];
  card._showTime = (t) => shown.push(t);
  card._render();
  const closed = root.innerHTML;
  const render = card._render.bind(card);
  card._render = () => { renders += 1; render(); };
  ACTION;
  return { closed, html: root.innerHTML, shown, open: card._splitsOpen, picked: card._splitPicked, renders, button, place: place.innerHTML };
})()
"""


def _split(km_m, secs, start=0):
    return {
        "distance_m": km_m,
        "active_s": secs,
        "start": start,
        "end": start + secs,
        "speed_kmh": None,
        "hr_avg": 100,
        "hr_max": 110,
    }


def _render(splits, sport="foot", action="", bars=()):
    summary = {
        "id": "A",
        "name": "x",
        "start": "2026-11-03T08:00:00+01:00",
        "sport": sport,
    }
    return js(
        CARD.replace("SUMMARY", json.dumps(summary))
        .replace("SPLITS", json.dumps(splits))
        .replace("ACTION", action)
        .replace("BARS", json.dumps(list(bars)))
    )


THREE = [_split(1000, 600, 0), _split(1000, 540, 600), _split(610, 400, 1140)]


def test_bars_and_closed_table():
    got = _render(THREE)
    html = got["closed"]
    # Verlauf und Kilometer je in einer Unterkarte
    assert html.count('class="unterkarte"') == 2
    # Drei Balken, Tabelle zu, Knopf "Tabelle"
    assert html.count('data-km="') == 3
    assert "<table" not in html and 'aria-expanded="false">Tabelle</button>' in html
    # Bis 12 Abschnitte: Wert ueber dem Balken (zu Fuss als min/km)
    assert (
        '<span class="v">10:00</span>' in html and '<span class="v">9:00</span>' in html
    )
    # Schnellster und langsamster ganzer Kilometer; der angefangene zaehlt nicht
    assert "schnellster km 2: 9:00 min/km · langsamster km 1: 10:00 min/km" in html
    # Schnellster rosa markiert; angefangener Kilometer schmaler
    assert 'class="balken schnell" data-km="1"' in html
    assert (
        'data-km="2" style="flex-grow:0.61"' in html
        and 'data-km="1" style="flex-grow:1"' in html
    )


def test_cycling_values_in_kmh():
    got = _render(THREE, sport="cycling")
    assert "schnellster km 2: 6,7 km/h · langsamster km 1: 6,0 km/h" in got["closed"]
    assert '<span class="v">6,7</span>' in got["closed"]


def test_long_ride_axis_every_ten_km():
    splits = [_split(1000, 120 + i, i * 200) for i in range(53)]
    html = _render(splits, sport="cycling")["closed"]
    assert html.count('data-km="') == 53
    # Keine Werte ueber 53 Balken, Beschriftung nur bei 10, 20 … 50 km
    assert '<span class="v">' not in html
    axis = html[html.index('class="km-achse"') :]
    labels = [part.split("<")[0] for part in axis.split('">')[1:] if part.split("<")[0]]
    assert labels == ["10", "20", "30", "40", "50"]


def test_toggle_table():
    got = _render(THREE, action="handlers.tabelle()")
    assert got["open"] is True
    # Nur die Tabelle wird eingesetzt, die Karte nicht neu gezeichnet (Leaflet
    # behielte sonst den Zoom nicht)
    assert got["renders"] == 0
    assert got["place"].startswith('<div class="tabelle"><table>')
    assert got["place"].count("<tr>") == 4 and "<td>1–2 km</td>" in got["place"]
    assert got["button"]["textContent"] == "Tabelle ausblenden"
    assert got["button"]["attrs"] == {"aria-expanded": "true"}
    # Zweiter Druck klappt wieder zu
    got = _render(THREE, action="handlers.tabelle(); handlers.tabelle()")
    assert got["open"] is False and got["place"] == ""
    assert got["button"]["textContent"] == "Tabelle"


def test_open_table_stays_open_after_render():
    got = _render(THREE, action="card._splitsOpen = true; card._render()")
    assert '<div class="tabelle-platz"><div class="tabelle"><table>' in got["html"]
    assert 'aria-expanded="true">Tabelle ausblenden</button>' in got["html"]


def test_new_workout_clears_picked_bar():
    got = _render(
        THREE, action="handlers.km1(); card._prepare({ splits: [] })", bars=(0, 1, 2)
    )
    assert got["picked"] is None


def test_tap_on_bar_shows_split_middle():
    got = _render(THREE, action="handlers.km1()", bars=(0, 1, 2))
    # Abschnitt 2 laeuft von 600 bis 1140 s: Mitte 870
    assert got["shown"] == [870]
    assert got["picked"] == 1


FILTER = r"""
(async () => {
  const calls = [];
  const card = new HaTrainingCard();
  card.shadowRoot = { getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] };
  card.setConfig = card.setConfig.bind(card);
  card.attachShadow = () => card.shadowRoot;
  card._renderShell = () => {};
  card.setConfig(CONFIG);
  card._render = () => {};
  card._hass = { language: "de", locale: { language: "de" }, callWS: async (req) => { calls.push(req); return req.type === "ha_training/workouts" ? { workouts: WORKOUTS, sports: SPORTS } : { summary: { id: req.workout_id }, detail: null }; } };
  await card._loadList();
  const bar = card._filterBar();
  ACTION
  return { calls, bar, filter: card._sportFilter, selected: card._selected };
})()
"""


def _filter(config=None, sports=None, workouts=None, action=""):
    return js(
        FILTER.replace("CONFIG", json.dumps(config or {}))
        .replace("SPORTS", json.dumps(sports or {}))
        .replace("WORKOUTS", json.dumps(workouts or [{"id": "W1"}]))
        .replace("ACTION", action)
    )


def test_filter_only_with_two_sports():
    assert _filter(sports={"foot": 3})["bar"] == ""
    bar = _filter(sports={"foot": 3, "cycling": 1})["bar"]
    assert 'data-f="" aria-pressed="true">Alle' in bar
    assert 'data-f="foot" aria-pressed="false">Zu Fuß' in bar
    assert 'data-f="cycling" aria-pressed="false">Radfahren' in bar
    assert "Schwimmen" not in bar


def test_config_sport_presets_filter_and_request():
    got = _filter(config={"sport": "cycling"}, sports={"foot": 3, "cycling": 1})
    assert got["filter"] == "cycling"
    assert got["calls"][0] == {
        "type": "ha_training/workouts",
        "limit": 30,
        "sport": "cycling",
    }
    assert 'data-f="cycling" aria-pressed="true"' in got["bar"]
    # Unbekannte Sportart in der Konfiguration: kein Filter
    assert _filter(config={"sport": "tennis"})["filter"] is None


def test_filter_click_loads_newest_of_sport():
    action = r"""
  const handlers = {};
  const root = { querySelectorAll: (sel) => (sel === "[data-f]" ? [{ dataset: { f: "cycling" }, addEventListener: (_, fn) => { handlers.f = fn; } }] : []) };
  card._selected = "ALT";
  card._bindFilter(root);
  calls.length = 0;
  handlers.f();
  await new Promise((r) => setTimeout(r, 0));
"""
    got = _filter(sports={"foot": 3, "cycling": 1}, action=action)
    assert got["filter"] == "cycling"
    assert got["selected"] is None
    assert got["calls"][0]["sport"] == "cycling"


def test_empty_sport_shows_hint():
    html = js(
        r"""
(() => {
  const root = { innerHTML: "", querySelectorAll: () => [] };
  const card = new HaTrainingCard();
  card.shadowRoot = { getElementById: () => root };
  card._config = {};
  card._hass = { language: "de", locale: { language: "de" }, config: {} };
  card._workouts = [];
  card._sports = { foot: 2, cycling: 1 };
  card._sportFilter = "swimming";
  card._summary = null;
  card._render();
  return root.innerHTML;
})()
"""
    )
    assert "Noch keine Trainings dieser Sportart." in html
    assert (
        'data-f="swimming"' not in html
    )  # nicht vorhanden, aber Filter bleibt sichtbar
    assert 'data-f="" aria-pressed="false">Alle' in html


async def test_websocket_sport_filter(
    hass: HomeAssistant, entry, hass_client, hass_ws_client
):
    walk = workout("G", datetime(2026, 10, 30, 9, 0, tzinfo=TZ))
    bike = workout(
        "R", datetime(2026, 10, 31, 9, 0, tzinfo=TZ), name="Outdoor Radfahren"
    )
    await post(hass_client, payload(walk, bike))
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "ha_training/workouts"})
    result = (await ws.receive_json())["result"]
    assert [w["id"] for w in result["workouts"]] == ["R", "G"]
    assert result["sports"] == {"cycling": 1, "foot": 1}
    await ws.send_json({"id": 2, "type": "ha_training/workouts", "sport": "foot"})
    result = (await ws.receive_json())["result"]
    assert [w["id"] for w in result["workouts"]] == ["G"]
    # Anzahl je Sportart immer ueber alle Trainings
    assert result["sports"] == {"cycling": 1, "foot": 1}
    await ws.send_json({"id": 3, "type": "ha_training/workouts", "sport": "tennis"})
    assert (await ws.receive_json())["success"] is False


FORM = r"""
(() => {
  globalThis.document = { querySelector: (sel) => (sel === "html" ? { getAttribute: () => LANG } : null) };
  const form = CLS.getConfigForm();
  return {
    names: form.schema.map((f) => f.name),
    options: form.schema.map((f) => (f.selector.select ? f.selector.select.options.map((o) => o.value) : null)),
    optionLabels: form.schema.map((f) => (f.selector.select ? f.selector.select.options.map((o) => o.label) : null)),
    labels: form.schema.map((f) => form.computeLabel(f)),
    element: typeof CLS.getConfigElement,
  };
})()
"""


def _form(cls="HaTrainingCard", lang="de"):
    return js(FORM.replace("CLS", cls).replace("LANG", json.dumps(lang)))


def test_training_card_form():
    got = _form()
    # Formular von Home Assistant (getConfigForm), kein eigenes Element
    assert got["element"] == "undefined"
    assert got["names"] == [
        "workout",
        "color_by",
        "sport",
        "tile_url",
        "tile_attribution",
    ]
    assert got["options"][1] == ["speed", "heart_rate"]
    assert got["options"][2] == ["all", "foot", "cycling", "swimming", "other"]
    assert got["optionLabels"][2] == [
        "Alle",
        "Zu Fuß",
        "Radfahren",
        "Schwimmen",
        "Sonstige",
    ]
    assert got["labels"][1] == "Route einfärben nach"
    # Sprache der Oberflaeche; unbekannte Sprache und keine Angabe: Englisch
    assert _form(lang="en")["labels"][1] == "Colour route by"
    assert _form(lang="fr")["labels"][1] == "Colour route by"
    assert _form(lang=None)["labels"][1] == "Colour route by"


def test_records_card_form():
    got = _form("HaTrainingRecordsCard")
    assert got["element"] == "undefined"
    assert got["names"] == ["sport"]
    assert got["options"] == [["auto", "foot", "cycling", "swimming"]]
    assert got["labels"] == ["Sportart beim Öffnen"]


def test_editor_values_mean_no_option():
    # Der Editor schreibt „all“ bzw. „auto“ in die Konfiguration: wie ohne Option
    assert _filter(config={"sport": "all"})["filter"] is None
    # „auto“ (aus dem Editor) wie ohne Option: erste Sportart mit Bestleistung
    assert (
        'data-s="foot" aria-pressed="true"'
        in _records_card(config={"sport": "auto"})["html1"]
    )


@pytest.mark.parametrize("cls", ["HaTrainingCard", "HaTrainingRecordsCard"])
def test_grid_options(cls):
    assert js(f"new {cls}().getGridOptions()") == {"columns": 12, "min_columns": 6}


def test_bars_use_apple_speed_like_table():
    # 0.1.19: Live 03.11. zeigte der Balken 94,7 km/h (1000 m / 38 s), die
    # Tabelle Apples 95,4 km/h. active_s ist auf ganze Sekunden gerundet, der
    # Balken nimmt deshalb wie die Tabelle das Tempo von Apple.
    splits = [
        {**_split(1000, 72, 0), "speed_kmh": 50.1},
        {**_split(1000, 38, 72), "speed_kmh": 95.4},
        {**_split(1000, 535, 110), "speed_kmh": 6.73},
    ]
    got = _render(splits, sport="cycling", action="handlers.tabelle()")
    html = got["closed"]
    assert (
        '<span class="v">95,4</span>' in html and '<span class="v">50,1</span>' in html
    )
    assert "schnellster km 2: 95,4 km/h · langsamster km 3: 6,7 km/h" in html
    assert 'aria-label="Abschnitt 2 km: 95,4 km/h"' in html
    # Tabelle und Balken nennen denselben Wert
    assert "95,4 <small>km/h</small>" in got["place"]
    # Ohne Tempo von Apple: aus Strecke und Zeit
    assert (
        '<span class="v">94,7</span>'
        in _render([_split(1000, 38)], sport="cycling")["closed"]
    )


def test_foot_bars_keep_pace_from_time():
    # Zu Fuss bleibt min/km aus der Zeit (wie in der Tabelle), die Hoehe des
    # Balkens folgt dem Tempo von Apple
    splits = [
        {**_split(1000, 600, 0), "speed_kmh": 6.2},
        {**_split(1000, 540, 600), "speed_kmh": 6.5},
    ]
    html = _render(splits)["closed"]
    assert (
        '<span class="v">10:00</span>' in html and '<span class="v">9:00</span>' in html
    )
    assert "schnellster km 2: 9:00 min/km" in html
