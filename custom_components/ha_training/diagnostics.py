"""Diagnose ohne Webhook-ID, ohne Token und ohne Koordinaten.

Die Route zeigt Wohnort und Wege; sie bleibt deshalb ganz draussen. Von den
Details stehen nur Anzahlen in der Diagnose.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import TrainingConfigEntry
from .const import CONF_TOKEN, CONF_WEBHOOK_ID

TO_REDACT = {CONF_TOKEN, CONF_WEBHOOK_ID}
LATEST_COUNT = 5


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TrainingConfigEntry
) -> dict[str, Any]:
    store = entry.runtime_data.store
    latest = []
    for workout in store.workouts[:LATEST_COUNT]:
        detail = await store.async_get_detail(workout["id"]) or {}
        latest.append(
            {
                **workout,
                "detail": {
                    "route_points": len(detail.get("route") or []),
                    "heart_rate_points": len(detail.get("heart_rate") or []),
                    "pauses": len(detail.get("pauses") or []),
                    "splits": len(detail.get("splits") or []),
                    "steps": len(detail.get("steps") or []),
                },
            }
        )
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "workouts": len(store.workouts),
        "with_detail": sum(1 for w in store.workouts if w.get("has_detail")),
        "keep_details": store.keep_details,
        "latest": latest,
    }
