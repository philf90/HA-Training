"""0.1.23 (E10): Dienst ha_training.get_workouts mit Antwort.

Zusammenfassungen ohne Route, gefiltert nach Zeitraum und Sportart, mit
Summen ueber alle Treffer. Fuer alle angemeldeten Konten (dieselben Werte wie
die Sensoren), nicht nur fuer Administratoren.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
import voluptuous as vol
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.ha_training.const import DOMAIN

from .conftest import CENTER, TZ, payload, post, workout

WALK1 = workout("G1", datetime(2026, 10, 30, 15, 0, tzinfo=TZ))
WALK2 = workout("G2", datetime(2026, 11, 1, 9, 0, tzinfo=TZ))
RIDE = workout("R", datetime(2026, 11, 3, 8, 0, tzinfo=TZ), name="Outdoor Radfahren")


async def _call(hass, context=None, **data):
    return await hass.services.async_call(
        DOMAIN,
        "get_workouts",
        data,
        blocking=True,
        return_response=True,
        context=context,
    )


@pytest.fixture
async def three(hass: HomeAssistant, entry, hass_client):
    await post(hass_client, payload(WALK1, WALK2, RIDE))
    return entry


async def test_all_newest_first_with_totals(hass: HomeAssistant, three):
    result = await _call(hass)
    assert [w["id"] for w in result["workouts"]] == ["R", "G2", "G1"]
    assert [w["sport"] for w in result["workouts"]] == ["cycling", "foot", "foot"]
    assert result["count"] == 3
    totals = result["totals"]
    assert totals["workouts"] == 3
    one = result["workouts"][0]
    assert totals["distance_km"] == round(3 * one["distance_km"], 3)
    assert totals["duration_s"] == 3 * one["duration_s"]
    assert set(totals) == {
        "workouts",
        "distance_km",
        "duration_s",
        "active_kcal",
        "elevation_up_m",
    }


async def test_period_start_inclusive_end_exclusive(hass: HomeAssistant, three):
    result = await _call(hass, start="2026-11-01 09:00:00", end="2026-11-03 08:00:00")
    assert [w["id"] for w in result["workouts"]] == ["G2"]
    assert result["totals"]["workouts"] == 1


async def test_naive_time_in_home_assistant_zone(hass: HomeAssistant, three):
    # G1 beginnt 15:00 Ortszeit (14:00 UTC). "14:30" ohne Zone gilt als
    # Ortszeit; als UTC gelesen (15:30 Ortszeit) fiele G1 heraus.
    result = await _call(hass, start="2026-10-30 14:30:00", end="2026-10-31 00:00:00")
    assert [w["id"] for w in result["workouts"]] == ["G1"]
    # Mit Zone gilt die angegebene
    result = await _call(
        hass, start="2026-10-30T14:30:00+00:00", end="2026-10-31T00:00:00+01:00"
    )
    assert result["workouts"] == []


async def test_sport_filter(hass: HomeAssistant, three):
    result = await _call(hass, sport="cycling")
    assert [w["id"] for w in result["workouts"]] == ["R"]
    assert result["totals"]["workouts"] == 1
    assert (await _call(hass, sport="swimming"))["workouts"] == []
    with pytest.raises(vol.Invalid):
        await _call(hass, sport="tennis")


async def test_limit_but_totals_over_all(hass: HomeAssistant, three):
    result = await _call(hass, limit=1)
    assert [w["id"] for w in result["workouts"]] == ["R"]
    assert result["count"] == 1
    assert result["totals"]["workouts"] == 3
    # Alle Summen wie ohne Begrenzung
    assert result["totals"] == (await _call(hass))["totals"]
    with pytest.raises(vol.Invalid):
        await _call(hass, limit=0)
    with pytest.raises(vol.Invalid):
        await _call(hass, limit=501)


async def test_no_route_in_response(hass: HomeAssistant, three):
    result = await _call(hass)
    text = json.dumps(result)
    # Keine Koordinaten, keine Verlaeufe, kein internes Feld
    assert f"{CENTER[0]:.3f}"[:6] not in text and "latitude" not in text
    for w in result["workouts"]:
        assert not {"route", "heart_rate", "splits", "has_detail"} & set(w)


async def test_invalid_period(hass: HomeAssistant, three):
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, start="2026-11-03 00:00:00", end="2026-11-03 00:00:00")
    assert err.value.translation_key == "invalid_period"


async def test_read_only_user_may_query(
    hass: HomeAssistant, three, hass_read_only_user
):
    context = Context(user_id=hass_read_only_user.id)
    result = await _call(hass, context=context)
    assert result["totals"]["workouts"] == 3


async def test_response_required(hass: HomeAssistant, three):
    # Nur mit Antwort aufrufbar (SupportsResponse.ONLY)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "get_workouts", {}, blocking=True)
