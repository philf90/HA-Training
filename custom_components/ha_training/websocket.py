"""WebSocket-API fuer die Karte: Liste der Trainings und Details eines Trainings.

Nur angemeldete Nutzer erreichen sie (Anmeldung der WebSocket-Verbindung von
Home Assistant). Die Route verlaesst Home Assistant nur auf diesem Weg.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

if TYPE_CHECKING:
    from . import TrainingConfigEntry

MAX_LIST = 500


def _entry(hass: HomeAssistant, entry_id: str | None) -> TrainingConfigEntry | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        if entry_id is None or entry.entry_id == entry_id:
            return entry
    return None


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_workouts)
    websocket_api.async_register_command(hass, ws_workout)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/workouts",
        vol.Optional("entry_id"): str,
        vol.Optional("limit", default=50): vol.All(int, vol.Range(1, MAX_LIST)),
    }
)
@callback
def ws_workouts(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Zusammenfassungen, neuestes Training zuerst."""
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Kein Eintrag geladen")
        return
    workouts = entry.runtime_data.store.workouts[: msg["limit"]]
    connection.send_result(
        msg["id"], {"entry_id": entry.entry_id, "workouts": workouts}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/workout",
        vol.Required("workout_id"): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_workout(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Zusammenfassung und Details eines Trainings."""
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Kein Eintrag geladen")
        return
    store = entry.runtime_data.store
    summary = store.get(msg["workout_id"])
    if summary is None:
        connection.send_error(msg["id"], "not_found", "Training nicht gefunden")
        return
    detail = await store.async_get_detail(msg["workout_id"])
    connection.send_result(msg["id"], {"summary": summary, "detail": detail})
