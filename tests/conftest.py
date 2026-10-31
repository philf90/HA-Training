"""Gemeinsame Hilfen: synthetische Trainings im Format von Health Auto Export.

Die Route ist erfunden: ein Kreis um einen oeffentlichen Ort (Grosser Stern,
Berlin). Echte Koordinaten gehoeren nie in das Repo (test_datenschutz.py).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_training.const import CONF_WEBHOOK_ID, DOMAIN

CENTER = (52.5145, 13.3501)
WEBHOOK_ID = "test-webhook-geheim"
TZ = timezone(timedelta(hours=1))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S %z")


def workout(
    workout_id: str = "TEST-0001",
    start: datetime | None = None,
    minutes: int = 30,
    pause: tuple[int, int] | None = (10, 13),
    name: str = "Outdoor Spaziergang",
) -> dict[str, Any]:
    """Ein Training: Kreis von ~2,5 km, ein Punkt pro Sekunde, Puls je Minute."""
    start = start or datetime(2026, 10, 30, 15, 0, 0, tzinfo=TZ)
    end = start + timedelta(minutes=minutes)
    route = []
    seconds = minutes * 60
    radius = 0.0036
    for i in range(0, seconds, 1):
        if pause and pause[0] * 60 <= i < pause[1] * 60:
            continue
        angle = 2 * math.pi * i / seconds
        route.append(
            {
                "latitude": CENTER[0] + radius * math.sin(angle),
                "longitude": CENTER[1] + radius * 1.6 * math.cos(angle),
                "altitude": 35 + math.sin(angle * 3),
                "speed": 1.2 + 0.2 * math.sin(angle * 5),
                "course": 90.0,
                "courseAccuracy": 5.0,
                "horizontalAccuracy": 1.2,
                "verticalAccuracy": 1.5,
                "speedAccuracy": 0.3,
                "timestamp": fmt(start + timedelta(seconds=i)),
            }
        )
    heart = [
        {
            "date": fmt(start + timedelta(minutes=m)),
            "Min": 95 + m % 7,
            "Avg": 100 + m % 9,
            "Max": 105 + m % 11,
            "units": "count/min",
            "source": "",
        }
        for m in range(minutes)
    ]
    events = []
    if pause:
        events = [
            {"type": "pause", "start": fmt(start + timedelta(minutes=pause[0]))},
            {"type": "resume", "start": fmt(start + timedelta(minutes=pause[1]))},
        ]
    first_km_end = start + timedelta(minutes=14)
    return {
        "id": workout_id,
        "name": name,
        "start": fmt(start),
        "end": fmt(end),
        "duration": seconds - (pause[1] - pause[0]) * 60 if pause else seconds,
        "location": "Outdoor",
        "isIndoor": False,
        "distance": {"qty": 2.5, "units": "km"},
        "speed": {"qty": 3.4, "units": "km/hr"},
        "maxSpeed": {"qty": 5.1, "units": "km"},
        "activeEnergyBurned": {"qty": 418.4, "units": "kJ"},
        "totalEnergy": {"qty": 836.8, "units": "kJ"},
        "elevationUp": {"qty": 6.0, "units": "m"},
        "heartRate": {
            "min": {"qty": 95, "units": "count/min"},
            "avg": {"qty": 104.0, "units": "count/min"},
            "max": {"qty": 115, "units": "count/min"},
        },
        "avgHeartRate": {"qty": 104.0, "units": "count/min"},
        "maxHeartRate": {"qty": 115, "units": "count/min"},
        "stepCadence": {"qty": 98.0, "units": "count/min"},
        "intensity": {"qty": 3.1, "units": "kcal/hr·kg"},
        "temperature": {"qty": 11.5, "units": "degC"},
        "humidity": {"qty": 70, "units": "%"},
        "estimatedEffortScore": {"qty": 3, "units": "appleEffortScore"},
        "route": route,
        "heartRateData": heart,
        "heartRateRecovery": [
            {"date": fmt(end + timedelta(seconds=10)), "Min": 99, "Avg": 99, "Max": 99}
        ],
        "events": events,
        "activities": [{"elapsedDuration": float(seconds)}],
        "splits": [
            {
                "targetDistance": {"units": "km", "qty": 1},
                "items": [
                    {
                        "start": fmt(start),
                        "end": fmt(first_km_end),
                        "activeDuration": 660.0,
                        "metrics": {
                            "distance": {"qty": 1000.0, "units": "m"},
                            "speed": {"qty": 1.25, "units": "m/s"},
                            "heartRateMaximum": {"qty": 112, "units": "bpm"},
                        },
                    },
                    {
                        "start": fmt(first_km_end),
                        "end": fmt(end),
                        "metrics": {
                            "distance": {"qty": 1500.0, "units": "m"},
                            "speed": {"qty": 1.3, "units": "m/s"},
                            "heartRateMaximum": {"qty": 115, "units": "bpm"},
                        },
                    },
                ],
            }
        ],
        "stepCount": [
            {"date": fmt(start + timedelta(minutes=m)), "qty": 100, "units": "count"}
            for m in range(minutes)
        ],
        "activeEnergy": [
            {"date": fmt(start + timedelta(minutes=m)), "qty": 14.0, "units": "kJ"}
            for m in range(minutes)
        ],
        "metadata": {},
    }


def payload(*workouts: dict[str, Any]) -> dict[str, Any]:
    return {"data": {"metrics": [], "workouts": list(workouts)}}


@pytest.fixture
async def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Eingerichteter Eintrag mit bekannter Webhook-ID (Zeitzone wie zu Hause)."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    config_entry = MockConfigEntry(
        domain=DOMAIN, title="Training", data={CONF_WEBHOOK_ID: WEBHOOK_ID}
    )
    config_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return config_entry


async def post(hass_client, body: Any, raw: bool = False):
    client = await hass_client()
    if raw:
        return await client.post(f"/api/webhook/{WEBHOOK_ID}", data=body)
    return await client.post(f"/api/webhook/{WEBHOOK_ID}", json=body)
