"""Schutzzone um Zuhause (E8) und feste Fehlercodes des Webhooks (V10)."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from itertools import pairwise

import pytest
from homeassistant.core import HomeAssistant

from custom_components.ha_training.const import (
    CONF_KEEP_DETAILS,
    CONF_PRIVACY_RADIUS,
    CONF_REQUIRE_TOKEN,
    CONF_ROUTE_USERS,
)
from custom_components.ha_training.privacy import metres, trim_route

from .conftest import payload, post, workout
from .test_karte import js

FIELDS = ["t", "lat", "lon", "alt", "speed", "hacc"]
HOME = (52.5, 13.4)
# Etwa 10 m nach Norden je Schritt
STEP = 10 / 111_195


def _line(steps: list[int]) -> list[list]:
    """Punkte im Abstand steps[i] * 10 m noerdlich von HOME."""
    return [
        [1000 + i, HOME[0] + n * STEP, HOME[1], 30.0, 1.0, 5.0]
        for i, n in enumerate(steps)
    ]


def test_metres_matches_known_distance():
    # 0,001 Grad Breite sind rund 111,2 m
    assert metres(52.5, 13.4, 52.501, 13.4) == pytest.approx(111.2, abs=0.1)


def test_trim_start_and_end():
    # Hin bis 100 m und zurueck nach Hause
    steps = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
    route = _line(steps)
    kept, start_m, end_m, gaps = trim_route(route, FIELDS, HOME, 35)
    # Erster Punkt ausserhalb von 35 m ist der bei 40 m
    assert [r[0] for r in kept] == [r[0] for r in route[4:17]]
    assert all(metres(r[1], r[2], *HOME) > 35 for r in kept)
    assert start_m == pytest.approx(40, abs=0.1)
    assert end_m == pytest.approx(40, abs=0.1)
    assert gaps == []


def test_middle_pass_is_hidden():
    # Weg, mittendrin an Zuhause vorbei, wieder weg (0.1.13 zeigte das)
    steps = [10, 9, 8, 2, 0, 1, 8, 9, 10]
    route = _line(steps)
    kept, start_m, end_m, gaps = trim_route(route, FIELDS, HOME, 35)
    assert [r[0] for r in kept] == [r[0] for r in route[:3] + route[6:]]
    assert all(metres(r[1], r[2], *HOME) > 35 for r in kept)
    assert (start_m, end_m) == (0, 0)
    # Luecke vor dem 4. sichtbaren Punkt: 80 -> 20 -> 0 -> 10 -> 80 m
    assert gaps == [[3, pytest.approx(160, abs=0.2)]]


def test_several_gaps():
    steps = [10, 0, 10, 10, 1, 10]
    kept, _, _, gaps = trim_route(_line(steps), FIELDS, HOME, 35)
    assert len(kept) == 4
    assert [g[0] for g in gaps] == [1, 3]


def test_all_inside_and_off():
    route = _line([0, 1, 2, 1, 0])
    kept, start_m, _, gaps = trim_route(route, FIELDS, HOME, 35)
    assert kept == []
    assert gaps == []
    assert start_m == pytest.approx(40, abs=0.1)
    assert trim_route(route, FIELDS, HOME, 0) == (route, 0.0, 0.0, [])
    # Ohne Koordinatenfelder bleibt alles, wie es ist
    assert trim_route(route, ["t"], HOME, 35) == (route, 0.0, 0.0, [])


async def _setup(
    hass: HomeAssistant, entry, hass_client, radius: int, users=(), at: int = 0
):
    raw = workout()
    await post(hass_client, payload(raw))
    first = raw["route"][at]
    # Zuhause an einem Punkt der Testrunde (Kreis mit rund 400 m Radius), am
    # Start oder mittendrin
    hass.config.latitude = first["latitude"]
    hass.config.longitude = first["longitude"]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_KEEP_DETAILS: 200,
            CONF_REQUIRE_TOKEN: False,
            CONF_PRIVACY_RADIUS: radius,
            # Das Auswahlfeld gibt es nur, wenn es Konten ohne Adminrechte gibt
            **({CONF_ROUTE_USERS: list(users)} if users else {}),
        },
    )
    await hass.async_block_till_done()
    return (first["latitude"], first["longitude"])


async def _detail(ws, msg_id=1):
    await ws.send_json(
        {"id": msg_id, "type": "ha_training/workout", "workout_id": "TEST-0001"}
    )
    return (await ws.receive_json())["result"]["detail"]


async def _gpx_points(ws, msg_id) -> list[tuple[float, float]]:
    await ws.send_json(
        {"id": msg_id, "type": "ha_training/gpx", "workout_id": "TEST-0001"}
    )
    msg = await ws.receive_json()
    assert msg["success"]
    root = ET.fromstring(msg["result"]["gpx"])
    return [
        (float(p.get("lat")), float(p.get("lon")))
        for p in root.iter("{http://www.topografix.com/GPX/1/1}trkpt")
    ]


async def test_zone_trims_route_for_card(
    hass: HomeAssistant, entry, hass_client, hass_ws_client
):
    home = await _setup(hass, entry, hass_client, 200)
    store = entry.runtime_data.store
    full = (await store.async_get_detail("TEST-0001"))["route"]
    ws = await hass_ws_client(hass)
    detail = await _detail(ws)
    route = detail["route"]
    assert 0 < len(route) < len(full)
    # Kein ausgelieferter Punkt liegt in der Zone
    assert min(metres(r[1], r[2], *home) for r in route) > 200
    zone = detail["privacy"]
    assert zone["radius_m"] == 200
    assert zone["start_m"] > 200 and zone["end_m"] > 200

    # Weggelassen + sichtbar = ganze GPS-Strecke
    def length(rows):
        return sum(metres(a[1], a[2], b[1], b[2]) for a, b in pairwise(rows))

    assert zone["start_m"] + length(route) + zone["end_m"] == pytest.approx(
        length(full), abs=1
    )
    # Gespeichert bleibt die ganze Route
    assert len((await store.async_get_detail("TEST-0001"))["route"]) == len(full)


async def test_zone_off_by_default(
    hass: HomeAssistant, entry, hass_client, hass_ws_client
):
    await post(hass_client, payload(workout()))
    detail = await _detail(await hass_ws_client(hass))
    assert "privacy" not in detail
    assert len(detail["route"]) == 1620


async def test_gpx_full_for_admin_trimmed_for_shared_account(
    hass: HomeAssistant,
    entry,
    hass_client,
    hass_ws_client,
    hass_read_only_user,
    hass_read_only_access_token,
):
    home = await _setup(hass, entry, hass_client, 200, [hass_read_only_user.id])
    admin = await _gpx_points(await hass_ws_client(hass), 1)
    shared = await _gpx_points(
        await hass_ws_client(hass, hass_read_only_access_token), 2
    )
    assert len(admin) == 1620
    assert 0 < len(shared) < len(admin)
    assert min(metres(*p, *home) for p in shared) > 200
    assert min(metres(*p, *home) for p in admin) < 1


async def test_option_bounds(hass: HomeAssistant, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    field = next(k for k in schema if k == CONF_PRIVACY_RADIUS)
    assert field.default() == 0
    config = schema[field].config
    assert (config["min"], config["max"], config["unit_of_measurement"]) == (
        0,
        2000,
        "m",
    )


CARD = r"""
(() => {
  const card = new HaTrainingCard();
  card._hass = { language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" } };
  card._summary = { id: "A", distance_km: 3.0, start: "2026-10-30T15:00:00+01:00" };
  // 21 Punkte, je 100 m nach Norden; davor 450 m und danach 550 m in der Zone
  // (Marken fallen so mitten zwischen zwei Punkte, unabhaengig von Rundung)
  const route = Array.from({ length: 21 }, (_, i) => [1793000000 + i * 60, 52.5 + (i * 100) / 111195, 13.4, 30, 1.7, 5]);
  card._prepare({ route, heart_rate: [], pauses: PAUSES, privacy: { radius_m: 300, start_m: 450, end_m: 550 } });
  card._ll = card._points.map((p) => [p.lat, p.lon]);
  const fake = { addTo() { return this; }, bringToFront() {} };
  globalThis.window = { L: { circleMarker: () => fake, marker: () => fake, divIcon: () => ({}), layerGroup: () => fake } };
  card._map = { latLngToContainerPoint: () => ({ x: Math.random() * 1e6, y: 0 }), removeLayer() {} };
  card._color = () => "#000000";  // kein getComputedStyle in Node
  card._labels();
  return { first: card._points[0].d, last: card._points[20].d, total: card._gpsTotal, factor: card._dFactor, marks: card._marks.map(([i, t]) => [i, t]) };
})()
"""


def test_card_keeps_distance_with_zone():
    got = js(CARD.replace("PAUSES", "[]"))
    # Erster sichtbarer Punkt bei 450 m, Gesamt 450 + 2000 + 550 = 3000 m
    assert got["first"] == pytest.approx(450, abs=1)
    assert got["last"] == pytest.approx(2450, abs=2)
    assert got["total"] == pytest.approx(3000, abs=2)
    # Apple 3,0 km zu GPS 3,0 km: kein Strecken der Kilometer
    assert got["factor"] == pytest.approx(1, abs=0.001)
    texts = [t for _, t in got["marks"]]
    # Statt Start und Ziel mit Uhrzeit die Schutzzone
    assert texts[:2] == ["Schutzzone", "Schutzzone"]
    # Nur 1 km und 2 km liegen im sichtbaren Teil (0,45 bis 2,45 km)
    assert [t for t in texts if t.endswith(" km")] == ["1 km", "2 km"]
    marks = {t: i for i, t in got["marks"]}
    # Erster Punkt ab 1000 m ist Nr. 6 (1050 m), ab 2000 m Nr. 16 (2050 m)
    assert marks["1 km"] == 6 and marks["2 km"] == 16


def test_card_drops_pause_marks_inside_zone():
    # Pause vor dem ersten sichtbaren Punkt: keine Marke am Rand
    got = js(
        CARD.replace("PAUSES", "[[1792999000, 1792999100], [1793000300, 1793000360]]")
    )
    pauses = [t for _, t in got["marks"] if t.startswith("Pause")]
    assert len(pauses) == 1


def test_card_shows_zone_note():
    html = js(
        r"""
(() => {
  const root = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] };
  const card = new HaTrainingCard();
  card.shadowRoot = { getElementById: (id) => (id === "inhalt" ? root : null) };
  card._config = {};
  card._hass = { language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" }, user: { is_admin: false } };
  card._summary = { id: "A", name: "Outdoor Spaziergang", start: "2026-10-30T15:00:00+01:00", sport: "foot" };
  card._workouts = [card._summary];
  card._current = "A";
  card._points = [];
  card._detail = { route: [], heart_rate: [], privacy: { radius_m: 300, start_m: 1, end_m: 1 } };
  card._render();
  return root.innerHTML;
})()
"""
    )
    assert "im Umkreis von 300 m um Zuhause sind ausgeblendet" in html


@pytest.mark.parametrize(
    ("body", "status", "error"),
    [(b"{kaputt", 400, "invalid_json"), (b"", 400, "invalid_json")],
)
async def test_error_codes(
    hass: HomeAssistant, entry, hass_client, body, status, error
):
    response = await post(hass_client, body, raw=True)
    assert response.status == status
    assert (await response.json())["error"] == error


async def test_success_has_no_error_code(hass: HomeAssistant, entry, hass_client):
    response = await post(hass_client, payload(workout()))
    body = await response.json()
    assert response.status == 200
    assert "error" not in body
    assert math.isclose(body["neu"], 1)


def test_card_no_km_mark_from_inside_zone():
    # 1,45 km in der Zone: die Marke "1 km" laege im ausgeblendeten Teil und
    # saesse sonst am ersten sichtbaren Punkt
    got = js(
        CARD.replace("PAUSES", "[]")
        .replace("start_m: 450, end_m: 550", "start_m: 1450, end_m: 550")
        # Apple-Distanz passend zu 1450 + 2000 + 550 m, Faktor 1
        .replace("distance_km: 3.0", "distance_km: 4.0")
    )
    kms = [(i, t) for i, t in got["marks"] if t.endswith(" km")]
    assert kms == [(6, "2 km"), (16, "3 km")]


def test_card_same_text_once_when_edges_meet():
    # Rundkurs: beide Raender der Zone fallen auf dieselbe Stelle der Karte
    html = js(
        CARD.replace("PAUSES", "[]")
        .replace(
            "latLngToContainerPoint: () => ({ x: Math.random() * 1e6, y: 0 })",
            "latLngToContainerPoint: () => ({ x: 0, y: 0 })",
        )
        .replace(
            "divIcon: () => ({})", "divIcon: (o) => { icons.push(o.html); return {}; }"
        )
        .replace(
            "(() => {\n  const card", "(() => {\n  const icons = [];\n  const card"
        )
        .replace("return { first:", "return icons; const unused = { first:")
    )
    assert len(html) == 1
    assert html[0].count("Schutzzone") == 1


async def test_zone_hides_middle_pass(
    hass: HomeAssistant, entry, hass_client, hass_ws_client
):
    # Zuhause auf halber Runde: Anfang und Ende liegen ausserhalb, die
    # Durchfahrt mittendrin muss trotzdem fehlen
    home = await _setup(hass, entry, hass_client, 200, at=1200)
    full = (await entry.runtime_data.store.async_get_detail("TEST-0001"))["route"]
    detail = await _detail(await hass_ws_client(hass))
    route, zone = detail["route"], detail["privacy"]
    assert min(metres(r[1], r[2], *home) for r in route) > 200
    assert (zone["start_m"], zone["end_m"]) == (0, 0)
    assert len(zone["gaps"]) == 1
    index, hidden = zone["gaps"][0]
    assert hidden > 400  # durch einen Kreis von 200 m Radius

    # Sichtbar + Luecke = ganze GPS-Strecke
    def length(rows):
        return sum(metres(a[1], a[2], b[1], b[2]) for a, b in pairwise(rows))

    visible = length(route[:index]) + hidden + length(route[index:])
    assert visible == pytest.approx(length(full), abs=1)


async def _segments(ws, msg_id) -> int:
    await ws.send_json(
        {"id": msg_id, "type": "ha_training/gpx", "workout_id": "TEST-0001"}
    )
    root = ET.fromstring((await ws.receive_json())["result"]["gpx"])
    return len(list(root.iter("{http://www.topografix.com/GPX/1/1}trkseg")))


async def test_gpx_new_segment_at_zone_gap(
    hass: HomeAssistant,
    entry,
    hass_client,
    hass_ws_client,
    hass_read_only_user,
    hass_read_only_access_token,
):
    await _setup(hass, entry, hass_client, 200, [hass_read_only_user.id], at=1200)
    # Testrunde hat eine Pause (zwei Segmente); die Luecke der Zone ein drittes
    assert await _segments(await hass_ws_client(hass), 1) == 2
    shared = await hass_ws_client(hass, hass_read_only_access_token)
    assert await _segments(shared, 2) == 3


def test_gpx_breaks_at_short_gap():
    # Durchfahrt kuerzer als 10 s: ohne Angabe der Luecke liefe die Linie
    # quer durch den Kreis
    from custom_components.ha_training.gpx import build_gpx

    route = _line([10, 11, 12, 13])
    detail = {
        "route_fields": FIELDS,
        "route": route,
        "privacy": {"radius_m": 35, "start_m": 0, "end_m": 0, "gaps": [[2, 50.0]]},
    }
    text = build_gpx({"name": "Test"}, detail)
    assert text.count("<trkseg>") == 2


CARD_GAP = r"""
(async () => {
  const card = new HaTrainingCard();
  card._hass = { language: "de", locale: { language: "de" }, config: { time_zone: "Europe/Berlin" } };
  card._config = {};
  card._colorBy = "speed";
  card.shadowRoot = { getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] };
  card._summary = { id: "A", distance_km: 3.7, start: "2026-10-30T15:00:00+01:00" };
  // 21 Punkte je 100 m nach Norden, 1 s Abstand; vor Punkt 10 eine Luecke der
  // Zone mit 800 m Strecke (auf der Karte nur 100 m Abstand)
  const route = Array.from({ length: 21 }, (_, i) => [1793000000 + i, 52.5 + (i * 100) / 111195, 13.4, 30, 1.7, 5]);
  card._prepare({ route, heart_rate: [], pauses: [[1793000009, 1793000009]], privacy: { radius_m: 300, start_m: 450, end_m: 550, gaps: [[10, 800]] } });
  card._color = () => "#000000";
  const any = new Proxy(function () {}, { get: (t, k) => (k === "then" ? undefined : k === "x" || k === "y" ? 0 : any), apply: () => any });
  globalThis.window = { L: any };
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  card._removeMap = () => {};
  await card._initMap({ isConnected: true });
  card._dots = null;
  card._map = { latLngToContainerPoint: () => ({ x: Math.random() * 1e6, y: 0 }), removeLayer() {} };
  card._labels();
  return { d: card._points.map((p) => Math.round(p.d)), total: Math.round(card._gpsTotal), parts: card._parts.map((p) => [p[0], p[p.length - 1]]), marks: card._marks.map(([i, t]) => [i, t]) };
})()
"""


def test_card_gap_in_zone():
    got = js(CARD_GAP)
    # Strecke: 450 m vor der Zone, dann je 100 m, an der Luecke 800 m
    assert got["d"][9] == 1350 and got["d"][10] == 2150
    assert got["total"] == 3150 + 550
    # Linie an der Luecke getrennt, obwohl nur 1 s dazwischen liegt
    assert got["parts"] == [[0, 9], [10, 20]]
    marks = got["marks"]
    zone = sorted(i for i, t in marks if t == "Schutzzone")
    assert zone == [0, 9, 10, 20]
    kms = [(i, t) for i, t in marks if t.endswith(" km")]
    # 2 km liegt in der Luecke (1,35 bis 2,15 km): keine Marke am Rand
    assert kms == [(6, "1 km"), (19, "3 km")]
    # Die Pause bei Sekunde 9 liegt vor der Luecke, nicht darin: bleibt
    assert any(t.startswith("Pause") for _, t in marks)


def test_card_drops_pause_in_gap():
    got = js(
        CARD_GAP.replace("[[1793000009, 1793000009]]", "[[1793000009.5, 1793000010]]")
    )
    assert not any(t.startswith("Pause") for _, t in got["marks"])


@pytest.mark.parametrize(
    ("peak", "shown"),
    [
        # Puls-Max + 30 s faellt zwischen Punkt 9 und 10, also in die Luecke
        (1792999979.5, False),
        # Gegenkontrolle: 30 s vor Punkt 5, sichtbar
        (1792999975, True),
    ],
)
def test_card_hr_peak_in_gap(peak, shown):
    got = js(
        CARD_GAP.replace(
            "heart_rate: []",
            f"heart_rate: [[{peak}, 100, 150, 160], [1793000020, 90, 100, 110]]",
        )
    )
    assert any(t.startswith("Puls-Max") for _, t in got["marks"]) is shown
