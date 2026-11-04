"""Dienste: ein Training loeschen oder ein geloeschtes wieder annehmen; Trainings
abfragen (E10).

Loeschen und wieder annehmen nur fuer Administratoren
(async_register_admin_service). Die Karte nutzt dieselben Funktionen ueber die
WebSocket-API.

get_workouts antwortet mit den Zusammenfassungen (SupportsResponse.ONLY): fuer
Skripte, Berichte und Sprachassistenten. Ohne Route und Verlaeufe, also nur
Werte, die auch die Sensoren und die Karte jedem angemeldeten Konto zeigen;
deshalb fuer alle Konten wie die anderen Lese-Wege.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_UPDATED
from .parser import parse_time
from .sport import GROUPS, OTHER, sport_of

if TYPE_CHECKING:
    from . import TrainingConfigEntry

ATTR_WORKOUT_ID = "workout_id"
SERVICE_DELETE = "delete_workout"
SERVICE_UNDELETE = "undelete_workout"
SCHEMA = vol.Schema({vol.Required(ATTR_WORKOUT_ID): cv.string})

SERVICE_GET = "get_workouts"
ATTR_START = "start"
ATTR_END = "end"
ATTR_SPORT = "sport"
ATTR_LIMIT = "limit"
DEFAULT_LIMIT = 30
MAX_LIMIT = 500
GET_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_START): cv.datetime,
        vol.Optional(ATTR_END): cv.datetime,
        vol.Optional(ATTR_SPORT): vol.In([*GROUPS, OTHER]),
        vol.Optional(ATTR_LIMIT, default=DEFAULT_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_LIMIT)
        ),
    }
)
# Summen ueber alle Treffer (nicht nur die ersten "limit")
TOTALS = ("distance_km", "duration_s", "active_kcal", "elevation_up_m")


def _local(value: datetime | None) -> datetime | None:
    """Ohne Zeitzone (Auswahl im UI) gilt die Zeitzone von Home Assistant."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt_util.get_default_time_zone())


def query_workouts(
    workouts: list[dict[str, Any]],
    start: datetime | None = None,
    end: datetime | None = None,
    sport: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Trainings mit Beginn in [start, end), neuestes zuerst, mit Summen."""
    start, end = _local(start), _local(end)
    hits: list[dict[str, Any]] = []
    for summary in workouts:
        begin = parse_time(summary.get("start"))
        if begin is None:
            continue
        if (start is not None and begin < start) or (end is not None and begin >= end):
            continue
        group = sport_of(summary.get("name"))
        if sport is not None and group != sport:
            continue
        item = {k: v for k, v in summary.items() if k != "has_detail"}
        hits.append({**item, "sport": group})
    totals: dict[str, Any] = {"workouts": len(hits)}
    for key in TOTALS:
        values = [w[key] for w in hits if isinstance(w.get(key), (int, float))]
        totals[key] = round(sum(values), 3) if values else 0
    return {"workouts": hits[:limit], "count": min(len(hits), limit), "totals": totals}


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

    async def get(call: ServiceCall) -> ServiceResponse:
        start, end = call.data.get(ATTR_START), call.data.get(ATTR_END)
        if start is not None and end is not None and _local(end) <= _local(start):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_period"
            )
        return query_workouts(
            loaded_entry(hass).runtime_data.store.workouts,
            start,
            end,
            call.data.get(ATTR_SPORT),
            call.data[ATTR_LIMIT],
        )

    async_register_admin_service(hass, DOMAIN, SERVICE_DELETE, delete, SCHEMA)
    async_register_admin_service(hass, DOMAIN, SERVICE_UNDELETE, undelete, SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET,
        get,
        schema=GET_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
