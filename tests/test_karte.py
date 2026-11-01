"""Hilfsfunktionen der Karte (in Node ausgefuehrt) und feste Regeln im CSS."""

from __future__ import annotations

import itertools
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

CARD = (
    Path(__file__).parents[1]
    / "custom_components"
    / "ha_training"
    / "frontend"
    / "ha-training-card.js"
)
CARD_TEXT = CARD.read_text(encoding="utf-8")

HARNESS = """
const vm = require("vm");
const fs = require("fs");
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => true, define() {} },
  window: {},
  console,
  setTimeout,
  clearTimeout,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const out = vm.runInContext(process.argv[2], ctx);
// Ausdruecke duerfen ein Promise liefern (async Methoden der Karte)
Promise.resolve(out).then((value) => process.stdout.write(JSON.stringify(value)));
"""


def js(expression: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node fehlt")
    result = subprocess.run(
        [node, "-e", HARNESS, str(CARD), expression],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_speed_levels_from_workout():
    # 50 Sekunden Stopp, dann gleichmaessig 2,0 bis 4,0 km/h
    values = [0.5] * 50 + [round(2 + i * 0.01, 2) for i in range(201)]
    got = js(f"workoutLimits({json.dumps(values)}, 'speed')")
    assert got == {"limits": [1, 2.5, 3, 3.5], "relative": True}


def test_heart_rate_levels_from_workout():
    got = js(f"workoutLimits({json.dumps(list(range(100, 150)))}, 'heart_rate')")
    # Fuenftel: Index 9,8 / 19,6 / 29,4 / 39,2 der sortierten Werte
    assert got == {"limits": [110, 120, 129, 139], "relative": True}


def test_levels_stay_strictly_increasing():
    got = js("workoutLimits(Array(100).fill(3), 'speed')")
    assert got["limits"] == [1, 3, 3.1, 3.2]
    got = js("workoutLimits(Array(100).fill(104), 'heart_rate')")
    assert got["limits"] == [104, 105, 106, 107]


def test_few_values_fall_back_to_fixed_levels():
    got = js("workoutLimits([2, 3, null, 4], 'speed')")
    assert got == {"limits": [1, 2.5, 3.3, 3.8], "relative": False}


def test_runs_split_at_gaps_and_missing_values():
    rows = [[0, 1], [60, 2], [200, 3], [300, None], [310, 4], [320, 5]]
    got = js(f"splitRuns({json.dumps(rows)}, 90)")
    assert got == [[[0, 1], [60, 2]], [[200, 3]], [[310, 4], [320, 5]]]


def test_short_burst_stays_in_chart_but_not_in_route_colour():
    # 20 s schneller (5 km/h) mitten in gleichmaessigen 3 km/h
    times = list(range(121))
    values = [5 if 50 <= t < 70 else 3 for t in times]
    chart = js(f"medianSmooth({times}, {values}, SMOOTH_CHART_S)")
    colour = js(f"medianSmooth({times}, {values}, SMOOTH_COLOR_S)")
    assert chart[60] == 5, "Diagramm zeigt den kurzen Abschnitt"
    assert colour[60] == 3, "Farbe der Route bleibt ruhig"
    assert set(colour) == {3}


def test_smoothing_window_is_time_not_index():
    # Luecke von 98 s (Pause): beide Seiten bleiben getrennt; fehlende Werte
    # zaehlen nicht, ein Fenster ohne Wert ergibt null
    times = [0, 1, 2, 100, 101, 102, 300]
    values = [1, 1, 1, 5, 5, 5, None]
    assert js(f"medianSmooth({times}, {json.dumps(values)}, 30)") == [
        1,
        1,
        1,
        5,
        5,
        5,
        None,
    ]


def test_route_colour_uses_smoothed_speed():
    assert js("[SCALES.speed.field, SMOOTH_CHART_S, SMOOTH_COLOR_S]") == ["vc", 7, 30]


def test_distance_factor():
    # Apple 2,913 km, GPS-Strecke 3.020 m: Kilometer-Marken rutschen nach hinten
    assert js("distanceFactor(2.912755, 3020)") == pytest.approx(0.96449, abs=1e-5)
    assert js("distanceFactor(null, 3000)") == 1
    assert js("distanceFactor(2.9, 0)") == 1
    assert js("distanceFactor(10, 3000)") == 1


def _lab(hex_color: str) -> tuple[float, float, float]:
    rgb = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    r, g, b = lin
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def _delta_e_2000(c1: str, c2: str) -> float:
    l1, a1, b1 = _lab(c1)
    l2, a2, b2 = _lab(c2)
    cm = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(cm**7 / (cm**7 + 25**7)))
    a1p, a2p = a1 * (1 + g), a2 * (1 + g)
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1 = math.degrees(math.atan2(b1, a1p)) % 360
    h2 = math.degrees(math.atan2(b2, a2p)) % 360
    dh = h2 - h1
    if abs(dh) > 180:
        dh -= 360 * math.copysign(1, dh)
    d_l, d_c = l2 - l1, c2p - c1p
    d_h = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2))
    lm, cmp_ = (l1 + l2) / 2, (c1p + c2p) / 2
    hm = (h1 + h2) / 2 if abs(h1 - h2) <= 180 else (h1 + h2 + 360) / 2
    t = (
        1
        - 0.17 * math.cos(math.radians(hm - 30))
        + 0.24 * math.cos(math.radians(2 * hm))
        + 0.32 * math.cos(math.radians(3 * hm + 6))
        - 0.2 * math.cos(math.radians(4 * hm - 63))
    )
    s_l = 1 + 0.015 * (lm - 50) ** 2 / math.sqrt(20 + (lm - 50) ** 2)
    s_c = 1 + 0.045 * cmp_
    s_h = 1 + 0.015 * cmp_ * t
    r_t = (
        -2
        * math.sin(math.radians(60 * math.exp(-(((hm - 275) / 25) ** 2))))
        * math.sqrt(cmp_**7 / (cmp_**7 + 25**7))
    )
    return math.sqrt(
        (d_l / s_l) ** 2
        + (d_c / s_c) ** 2
        + (d_h / s_h) ** 2
        + r_t * (d_c / s_c) * (d_h / s_h)
    )


def test_delta_e_reference_pair():
    # Weiss gegen Schwarz: L* 100 gegen 0, ohne Buntheit
    assert _delta_e_2000("#ffffff", "#000000") == pytest.approx(100, abs=0.5)


@pytest.mark.parametrize("kind", ["speed", "heart_rate"])
def test_neighbouring_levels_are_distinct(kind: str):
    colors = js(f"SCALES.{kind}.ramp.map((role) => COLORS[role][1])")
    assert len(colors) == 5
    for a, b in itertools.pairwise(colors):
        assert _delta_e_2000(a, b) >= 16, (a, b)


def test_map_stays_below_the_app_bars():
    # Leaflet legt Ebenen auf z-index 400 bis 1000; ohne eigene Ebene der
    # Kartenflaeche liegen sie ueber Kopf- und Fussleiste von Home Assistant
    rule = re.search(r"\.karte \{([^}]*)\}", CARD_TEXT).group(1)
    assert "position: relative" in rule
    assert "z-index: 0" in rule
    assert "isolation: isolate" in rule


def test_marker_parts_do_not_wrap_inside():
    assert ".marke .teil { white-space: nowrap; }" in CARD_TEXT


def test_workout_id_is_escaped_in_selector():
    # Auch wenn eine unsichere ID im Speicher steht (z. B. aus 0.1.3), darf
    # sie in der Auswahl kein HTML erzeugen
    html = js(
        r"""
(() => {
  const root = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] };
  const card = new HaTrainingCard();
  card.shadowRoot = { getElementById: (id) => (id === "inhalt" ? root : null) };
  card._config = {};
  card._hass = { language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" } };
  card._workouts = [
    { id: "A-1", name: "Walk", start: "2026-10-30T15:00:00+01:00" },
    { id: 'x"><img src=x onerror="alert(1)">', name: "Walk", start: "2026-10-29T15:00:00+01:00" },
  ];
  card._summary = card._workouts[0];
  card._current = "A-1";
  card._points = [];
  card._detail = null;
  card._render();
  return root.innerHTML;
})()
"""
    )
    assert "<img" not in html
    assert 'value="x&quot;&gt;&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"' in html


CARD_WITH = r"""
(() => {
  const root = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] };
  const calls = [];
  const card = new HaTrainingCard();
  card.shadowRoot = { getElementById: (id) => (id === "inhalt" ? root : null) };
  card._config = {};
  card._hass = {
    language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" },
    user: { is_admin: ADMIN },
    callWS: async (req) => { calls.push(req); return { workouts: [] }; },
  };
  card._workouts = [{ id: "A-1", name: "Walk", start: "2026-10-30T15:00:00+01:00" }];
  card._summary = card._workouts[0];
  card._current = "A-1";
  card._points = [];
  card._detail = null;
  card._render();
  return { card, root, calls };
})()
"""


@pytest.mark.parametrize("admin", [True, False])
def test_delete_button_only_for_admins(admin):
    html = js(CARD_WITH.replace("ADMIN", str(admin).lower()) + ".root.innerHTML")
    assert ('data-a="del"' in html) is admin
    # Ohne Route kein GPX-Knopf
    assert 'data-a="gpx"' not in html


def test_delete_needs_second_click():
    got = js(
        "(async () => { const { card, calls } = "
        + CARD_WITH.replace("ADMIN", "true")
        + "; const first = await card._deleteClick();"
        " const before = calls.length;"
        " const second = await card._deleteClick();"
        " return { first, before, second, types: calls.map((c) => c.type),"
        " ids: calls.map((c) => c.workout_id) }; })()"
    )
    assert got["first"] == "confirm"
    assert got["before"] == 0
    assert got["second"] == "deleted"
    assert got["types"][0] == "ha_training/delete_workout"
    assert got["ids"][0] == "A-1"
    # Danach laedt die Karte die Liste neu
    assert "ha_training/workouts" in got["types"]


def test_delete_refused_without_admin():
    got = js(
        "(async () => { const { card, calls } = "
        + CARD_WITH.replace("ADMIN", "false")
        + "; const r1 = await card._deleteClick(); const r2 = await card._deleteClick();"
        " return { r1, r2, n: calls.length }; })()"
    )
    assert got == {"r1": "denied", "r2": "denied", "n": 0}


def test_hidden_detail_shows_hint():
    html = js(
        CARD_WITH.replace("ADMIN", "false")
        + ".card; (() => { const c = "
        + CARD_WITH.replace("ADMIN", "false")
        + "; c.card._hidden = true; c.card._render(); return c.root.innerHTML; })()"
    )
    assert "nicht freigegeben" in html
    assert "gelöscht (Aufbewahrung" not in html


FIXED = r"""
(async () => {
  const root = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] };
  const calls = [];
  const list = Array.from({ length: 60 }, (_, i) => ({
    id: `W-${i}`, name: "Walk", start: new Date(Date.UTC(2026, 9, 30) - i * 864e5).toISOString(),
  }));
  const card = new HaTrainingCard();
  card.shadowRoot = { getElementById: (id) => (id === "inhalt" ? root : null) };
  card._config = { workout: "WANTED" };
  card._selected = "WANTED";
  card._hass = {
    language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" },
    callWS: async (req) => {
      calls.push(req.type === "ha_training/workouts" ? "list" : req.workout_id);
      if (req.type === "ha_training/workouts") return { workouts: list.slice(0, req.limit) };
      const w = list.find((x) => x.id === req.workout_id);
      if (!w) throw new Error("not_found");
      return { summary: w, detail: null };
    },
  };
  await card._loadList();
  return { current: card._current, calls, message: card._message || null,
           firstOption: (root.innerHTML.match(/<option value="([^"]+)"/) || [])[1] || null };
})()
"""


def test_fixed_workout_older_than_list_is_loaded():
    got = js(FIXED.replace("WANTED", "W-40"))
    assert got["current"] == "W-40"
    # Direkt geladen, ohne Umweg ueber das neueste
    assert got["calls"] == ["list", "W-40"]
    assert got["message"] is None
    # In der Auswahl steht das eingestellte Training, obwohl es nicht unter
    # den letzten 30 ist
    assert got["firstOption"] == "W-40"


def test_missing_fixed_workout_falls_back_with_hint():
    got = js(FIXED.replace("WANTED", "W-999"))
    assert got["current"] == "W-0"
    assert got["calls"] == ["list", "W-999", "W-0"]
    assert got["message"] == "missing"


def test_tile_source_only_accepts_https_templates():
    got = js(
        """[
      tileSource({}),
      tileSource({ tile_url: "https://tiles.example.org/{z}/{x}/{y}.png", tile_attribution: "<b>Eigene</b> & Co" }),
      tileSource({ tile_url: "http://tiles.example.org/{z}/{x}/{y}.png" }),
      tileSource({ tile_url: "https://tiles.example.org/{z}/{x}.png" }),
      tileSource({ tile_url: "javascript:alert(1)//{z}{x}{y}" }),
      tileSource({ tile_url: 'https://x.org/{z}/{x}/{y}.png" onerror="alert(1)' }),
    ]"""
    )
    assert got[0]["url"] == "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    assert got[0]["custom"] is False
    assert got[1] == {
        "url": "https://tiles.example.org/{z}/{x}/{y}.png",
        "attribution": "&lt;b&gt;Eigene&lt;/b&gt; &amp; Co",
        "custom": True,
    }
    assert [g["custom"] for g in got[2:]] == [False, False, False, False]


def test_tile_layer_sends_origin_as_referer():
    assert 'const TILE_REFERRER = "strict-origin-when-cross-origin";' in CARD_TEXT
    assert "referrerPolicy: TILE_REFERRER," in CARD_TEXT


WATCH = r"""
(() => {
  const card = new HaTrainingCard();
  const calls = [];
  card._config = {};
  card.shadowRoot = { getElementById: () => null };
  card._loadList = () => { calls.push("load"); };
  const make = (rev, wid) => ({
    entities: { "sensor.a": { platform: "other" }, "sensor.training_letztes_training": { platform: "ha_training" } },
    states: { "sensor.training_letztes_training": { attributes: { workout_id: wid, revision: rev } } },
  });
  card.hass = make(1, "A");
  card.hass = make(1, "A");          // keine Aenderung
  card.hass = make(2, "A");          // dasselbe Training geaendert
  card.hass = make(2, "B");          // neues Training
  // Danach wird nicht mehr ueber alle Entitaeten gesucht
  const before = card._watchEntity;
  const h = make(3, "B");
  Object.defineProperty(h, "entities", { get() { throw new Error("gesucht"); } });
  card.hass = h;
  return { calls: calls.length, entity: before };
})()
"""


def test_card_reloads_on_revision_and_caches_entity():
    got = js(WATCH)
    # Erster Aufruf, Revision 2, neues Training, Revision 3
    assert got == {"calls": 4, "entity": "sensor.training_letztes_training"}
