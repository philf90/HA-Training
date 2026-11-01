"""Andere Sportarten: Distanz in Yards/Fuss, lesbare Achsen, Kilometer-Marken."""

from __future__ import annotations

import pytest

from custom_components.ha_training.parser import parse_workout

from .conftest import workout
from .test_karte import js


@pytest.mark.parametrize(
    ("qty", "unit", "km"),
    [
        (1640, "yd", 1.49962),  # 1640 yd Schwimmen
        (1640, "Yards", 1.49962),
        (5000, "ft", 1.524),
        (1500, "m", 1.5),
        (1.5, "km", 1.5),
        (1.5, "", 1.5),  # ohne Einheit wie bisher km
        (1, "mi", 1.609),
    ],
)
def test_distance_units(qty, unit, km):
    raw = workout()
    raw["distance"] = {"qty": qty, "units": unit}
    summary, _ = parse_workout(raw)
    assert summary["distance_km"] == pytest.approx(km, abs=0.001)


def test_unknown_distance_unit_is_missing_not_km():
    # Frueher galt jede unbekannte Einheit als km
    raw = workout()
    raw["distance"] = {"qty": 1640, "units": "furlong"}
    summary, _ = parse_workout(raw)
    assert summary["distance_km"] is None
    assert summary["pace_s_per_km"] is None


@pytest.mark.parametrize(
    ("lo", "hi", "expect"),
    [
        (0, 5, [0, 1, 2, 3, 4, 5]),  # Gehen
        (0, 35, [0, 10, 20, 30, 40]),  # Mountainbike
        (0, 62, [0, 20, 40, 60, 80]),  # Rennrad bergab
        (95, 115, [95, 100, 105, 110, 115]),  # Puls ruhig
        (62, 188, [50, 100, 150, 200]),  # Puls Intervall
    ],
)
def test_nice_ticks(lo, hi, expect):
    got = js(f"niceTicks({lo}, {hi}, 5)")
    assert got["ticks"] == expect
    assert got["lo"] <= lo and got["hi"] >= hi


def test_nice_ticks_never_crowded():
    # Fuer jede Obergrenze bis 300 km/h hoechstens sechs Beschriftungen
    counts = js(
        "Array.from({ length: 300 }, (_, i) => niceTicks(0, i + 1, 5).ticks.length)"
    )
    assert max(counts) <= 6


@pytest.mark.parametrize(
    ("km", "step"), [(3, 1), (19.9, 1), (20, 5), (49, 5), (50, 10), (99, 10), (100, 20)]
)
def test_km_mark_step(km, step):
    assert js(f"kmMarkStep({km})") == step


def test_marks_on_long_ride():
    # 100 km: 4 Marken (20, 40, 60, 80) statt 99
    got = js(
        """(() => {
      const card = new HaTrainingCard();
      card._hass = { language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" } };
      const n = 1001;
      card._points = Array.from({ length: n }, (_, i) => ({ t: 1793000000 + i * 10, d: i * 100, lat: 0, lon: 0 }));
      card._dFactor = 1;
      card._detail = { pauses: [], heart_rate: [] };
      const added = [];
      const fake = { addTo() { return this; }, bringToFront() {} };
      globalThis.window = { L: {
        circleMarker: () => fake, marker: () => fake, divIcon: () => ({}),
        layerGroup: () => fake,
      } };
      card._map = { latLngToContainerPoint: () => ({ x: Math.random() * 1e6, y: 0 }), removeLayer() {} };
      card._ll = card._points.map(() => [0, 0]);
      card._clock = () => "00:00";
      card._color = () => "#000000";  // kein getComputedStyle in Node
      card._labels();
      return card._marks.map(([, text]) => text).filter((t) => t.endsWith(" km"));
    })()"""
    )
    assert got == ["20 km", "40 km", "60 km", "80 km"]


def test_chart_labels_readable_for_cycling():
    # Diagramme wirklich zeichnen (nachgebildetes SVG) und die Beschriftungen
    # der y-Achse zaehlen: Puls 62-188 bpm, Tempo bis 35 km/h
    got = js(
        """(() => {
      const card = new HaTrainingCard();
      card._hass = { language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" } };
      card._color = () => "#000000";
      const t0 = 1793000000, n = 3600;
      card._summary = { start: new Date(t0 * 1000).toISOString(), end: new Date((t0 + n) * 1000).toISOString() };
      card._detail = { pauses: [], heart_rate: Array.from({ length: 60 }, (_, i) => [t0 + i * 60, 62 + i, 70 + i * 2, 188]) };
      card._points = Array.from({ length: n }, (_, i) => ({ t: t0 + i, v: 35 * (i % 100) / 100 }));
      card._charts = [];
      const svgs = {};
      const fakeSvg = (id) => ({ id, innerHTML: "", clientWidth: 320,
        getAttribute: () => (id === "#dHr" ? "140" : "120"),
        querySelector: () => ({ addEventListener() {}, setAttribute() {} }) });
      card._initCharts({ querySelector: (id) => (svgs[id] = svgs[id] || fakeSvg(id)) });
      const labels = (id) => (svgs[id].innerHTML.match(/text-anchor="end">[^<]*</g) || []).length;
      return { hr: labels("#dHr"), speed: labels("#dSpeed") };
    })()"""
    )
    assert 2 <= got["hr"] <= 6
    assert 2 <= got["speed"] <= 6
