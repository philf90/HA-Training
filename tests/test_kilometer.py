"""0.1.18: Kilometer als Balken mit aufklappbarer Tabelle (Variante C),
Verlauf in einer Unterkarte, Filter nach Sportart (E2), visueller Editor (V5)."""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from homeassistant.core import HomeAssistant

from .conftest import TZ, payload, post, workout
from .test_karte import js

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


EDITOR = r"""
(() => {
  globalThis.CustomEvent = class { constructor(type, init) { this.type = type; Object.assign(this, init); } };
  const forms = [];
  globalThis.document = { createElement: (tag) => { const el = { tag, listeners: {}, addEventListener(t, fn) { this.listeners[t] = fn; } }; forms.push(el); return el; } };
  const editor = new CLS();
  editor.appendChild = () => {};
  const events = [];
  editor.dispatchEvent = (e) => events.push(e.detail.config);
  editor.hass = { language: "de", locale: { language: "de" } };
  editor.setConfig(CONFIG);
  const form = forms.find((f) => f.tag === "ha-form");
  const labels = form.schema.map((f) => form.computeLabel(f));
  form.listeners["value-changed"]({ detail: { value: VALUE } });
  return { names: form.schema.map((f) => f.name), data: form.data, labels, events, tag: HaTrainingCard.getConfigElement().tag, recTag: HaTrainingRecordsCard.getConfigElement().tag };
})()
"""


def _editor(cls="HaTrainingCardEditor", config=None, value=None):
    return js(
        EDITOR.replace("CLS", cls)
        .replace("CONFIG", json.dumps(config or {"type": "custom:ha-training-card"}))
        .replace("VALUE", json.dumps(value or {}))
    )


def test_training_card_editor():
    got = _editor(
        value={
            "workout": "latest",
            "color_by": "heart_rate",
            "sport": "all",
            "tile_url": "",
            "tile_attribution": "",
        }
    )
    assert got["tag"] == "ha-training-card-editor"
    assert got["recTag"] == "ha-training-records-card-editor"
    assert got["names"] == [
        "workout",
        "color_by",
        "sport",
        "tile_url",
        "tile_attribution",
    ]
    assert got["data"]["workout"] == "latest" and got["data"]["sport"] == "all"
    assert got["labels"][1] == "Route einfärben nach"
    # Leere Felder fallen heraus, der Rest bleibt
    assert got["events"] == [
        {
            "type": "custom:ha-training-card",
            "workout": "latest",
            "color_by": "heart_rate",
        }
    ]


def test_records_card_editor():
    got = _editor(
        cls="HaTrainingRecordsCardEditor",
        config={"type": "custom:ha-training-records-card", "sport": "cycling"},
        value={"sport": "auto"},
    )
    assert got["names"] == ["sport"]
    assert got["data"] == {"sport": "cycling"}
    assert got["labels"] == ["Sportart beim Öffnen"]
    assert got["events"] == [{"type": "custom:ha-training-records-card"}]


@pytest.mark.parametrize("cls", ["HaTrainingCard", "HaTrainingRecordsCard"])
def test_grid_options(cls):
    assert js(f"new {cls}().getGridOptions()") == {"columns": 12, "min_columns": 6}


def test_editor_defaults_show_all_and_auto():
    # Ohne `sport` oder mit unbekanntem Wert zeigt das Feld „Alle“ bzw. „Automatisch“
    assert (
        _editor(config={"type": "custom:ha-training-card", "sport": "tennis"})["data"][
            "sport"
        ]
        == "all"
    )
    assert _editor(cls="HaTrainingRecordsCardEditor", config={"type": "x"})["data"] == {
        "sport": "auto"
    }
    # Eine Sportart bleibt in der Konfiguration stehen
    got = _editor(value={"sport": "swimming"})
    assert got["events"] == [{"type": "custom:ha-training-card", "sport": "swimming"}]
