"""Dienste: ein Training loeschen oder ein geloeschtes wieder annehmen.

Beide nur fuer Administratoren (async_register_admin_service). Die Karte nutzt
dieselben Funktionen ueber die WebSocket-API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN, SIGNAL_UPDATED

if TYPE_CHECKING:
    from . import TrainingConfigEntry

ATTR_WORKOUT_ID = "workout_id"
SERVICE_DELETE = "delete_workout"
SERVICE_UNDELETE = "undelete_workout"
SCHEMA = vol.Schema({vol.Required(ATTR_WORKOUT_ID): cv.string})


def loaded_entry(hass: HomeAssistant) -> TrainingConfigEntry:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="not_loaded"
    )


async def async_delete_workout(
    hass: HomeAssistant, entry: TrainingConfigEntry, workout_id: str
) -> dict[str, Any]:
    """Loeschen und Sensoren aktualisieren; unbekannte ID -> Fehler."""
    workout = await entry.runtime_data.store.async_delete(workout_id)
    if workout is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="workout_not_found",
            translation_placeholders={"workout_id": workout_id},
        )
    # Keine neuen Trainings, nur neu berechnen (letztes Training, Woche)
    async_dispatcher_send(hass, f"{SIGNAL_UPDATED}_{entry.entry_id}", [])
    return workout


async def async_undelete_workout(
    hass: HomeAssistant, entry: TrainingConfigEntry, workout_id: str
) -> None:
    if not await entry.runtime_data.store.async_undelete(workout_id):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="workout_not_deleted",
            translation_placeholders={"workout_id": workout_id},
        )


@callback
def async_register_services(hass: HomeAssistant) -> None:
    async def delete(call: ServiceCall) -> None:
        await async_delete_workout(
            hass, loaded_entry(hass), call.data[ATTR_WORKOUT_ID].strip()
        )

    async def undelete(call: ServiceCall) -> None:
        await async_undelete_workout(
            hass, loaded_entry(hass), call.data[ATTR_WORKOUT_ID].strip()
        )

    async_register_admin_service(hass, DOMAIN, SERVICE_DELETE, delete, SCHEMA)
    async_register_admin_service(hass, DOMAIN, SERVICE_UNDELETE, undelete, SCHEMA)
