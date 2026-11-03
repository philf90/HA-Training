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
    kept, start_m, end_m = trim_route(route, FIELDS, HOME, 35)
    # Erster Punkt ausserhalb von 35 m ist der bei 40 m
    assert [r[0] for r in kept] == [r[0] for r in route[4:17]]
    assert all(metres(r[1], r[2], *HOME) > 35 for r in kept)
    assert start_m == pytest.approx(40, abs=0.1)
    assert end_m == pytest.approx(40, abs=0.1)


def test_middle_pass_stays_visible():
    # Weg, mittendrin an Zuhause vorbei, wieder weg
    steps = [10, 9, 8, 0, 8, 9, 10]
    kept, start_m, end_m = trim_route(_line(steps), FIELDS, HOME, 35)
    assert len(kept) == 7
    assert (start_m, end_m) == (0, 0)


def test_all_inside_and_off():
    route = _line([0, 1, 2, 1, 0])
    kept, start_m, _ = trim_route(route, FIELDS, HOME, 35)
    assert kept == []
    assert start_m == pytest.approx(40, abs=0.1)
    assert trim_route(route, FIELDS, HOME, 0) == (route, 0.0, 0.0)
    # Ohne Koordinatenfelder bleibt alles, wie es ist
    assert trim_route(route, ["t"], HOME, 35) == (route, 0.0, 0.0)


async def _setup(hass: HomeAssistant, entry, hass_client, radius: int, users=()):
    raw = workout()
    await post(hass_client, payload(raw))
    first = raw["route"][0]
    # Zuhause am Startpunkt der Testrunde (Kreis mit rund 400 m Radius)
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
