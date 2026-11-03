"""WebSocket-API fuer die Karte: Liste, Details, Bestleistungen, GPX, Loeschen.

Nur angemeldete Nutzer erreichen sie (Anmeldung der WebSocket-Verbindung von
Home Assistant). Die Route verlaesst Home Assistant nur auf diesem Weg. Loeschen
nur fuer Administratoren. Route, Verlaeufe und GPX sehen Administratoren und die
Konten, die unter "Konfigurieren" freigegeben sind; alle anderen bekommen nur
die Zusammenfassung (dieselben Werte wie die Sensoren).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from . import rekorde
from .const import (
    CONF_PRIVACY_RADIUS,
    CONF_ROUTE_USERS,
    DEFAULT_PRIVACY_RADIUS,
    DOMAIN,
)
from .gpx import build_gpx, filename
from .privacy import apply_zone
from .sport import sport_of

if TYPE_CHECKING:
    from . import TrainingConfigEntry

MAX_LIST = 500


def _zone(
    hass: HomeAssistant, entry: TrainingConfigEntry, detail: dict[str, Any]
) -> dict[str, Any]:
    """Details mit Schutzzone um den Standort von Home Assistant (E8)."""
    radius = entry.options.get(CONF_PRIVACY_RADIUS, DEFAULT_PRIVACY_RADIUS)
    if not radius:
        return detail
    home = (hass.config.latitude, hass.config.longitude)
    return apply_zone(detail, home, float(radius))


def _with_sport(summary: dict[str, Any]) -> dict[str, Any]:
    """Kopie mit Sportgruppe fuer die Karte; berechnet, nicht gespeichert.

    So gilt sie auch fuer Trainings, die vor 0.1.12 gespeichert wurden, und
    die Erkennung steht nur an einer Stelle (sport.py).
    """
    return {**summary, "sport": sport_of(summary.get("name"))}


def _entry(hass: HomeAssistant, entry_id: str | None) -> TrainingConfigEntry | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        if entry_id is None or entry.entry_id == entry_id:
            return entry
    return None


def may_see_routes(entry: TrainingConfigEntry, user: Any) -> bool:
    """Administratoren immer, sonst nur freigegebene Konten."""
    if user is None:
        return False
    if user.is_admin:
        return True
    return user.id in entry.options.get(CONF_ROUTE_USERS, [])


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_workouts)
    websocket_api.async_register_command(hass, ws_workout)
    websocket_api.async_register_command(hass, ws_gpx)
    websocket_api.async_register_command(hass, ws_delete)
    websocket_api.async_register_command(hass, ws_records)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/records",
        vol.Optional("entry_id"): str,
    }
)
@callback
def ws_records(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Bestleistungen und Serien (rekorde.py) fuer die Karte.

    Fuer alle angemeldeten Konten wie die Liste: nur Werte, Name und Beginn
    eines Trainings, keine Route; dieselben Werte zeigen die Sensoren.
    """
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Kein Eintrag geladen")
        return
    # Entitaets-IDs der Sensoren (Sprache der Instanz, ggf. umbenannt): ein
    # Tipp auf eine Kachel der Karte "Bestleistungen" oeffnet deren Verlauf
    registry = er.async_get(hass)
    entities = {
        key: registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{sensor_key}"
        )
        for key, sensor_key in (
            *((key, f"record_{key}") for key in rekorde.RECORDS),
            (rekorde.STREAK, "streak"),
            (rekorde.STREAK_LONGEST, "streak_longest"),
        )
    }
    connection.send_result(
        msg["id"], {**rekorde.cached(entry.runtime_data.store), "entities": entities}
    )


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
    workouts = [
        _with_sport(w) for w in entry.runtime_data.store.workouts[: msg["limit"]]
    ]
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
    summary = _with_sport(summary)
    if not may_see_routes(entry, connection.user):
        # Zusammenfassung ja, Route und Verlaeufe nein
        connection.send_result(
            msg["id"], {"summary": summary, "detail": None, "detail_hidden": True}
        )
        return
    detail = await store.async_get_detail(msg["workout_id"])
    if detail:
        # Fuer alle Konten, auch Administratoren: die Karte laedt Kacheln fuer
        # das Gebiet der Route, und Dashboards laufen oft auf geteilten Geraeten
        detail = _zone(hass, entry, detail)
    connection.send_result(msg["id"], {"summary": summary, "detail": detail})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/gpx",
        vol.Required("workout_id"): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_gpx(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Route eines Trainings als GPX-Text mit Dateinamen."""
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Kein Eintrag geladen")
        return
    if not may_see_routes(entry, connection.user):
        connection.send_error(msg["id"], "unauthorized", "Route nicht freigegeben")
        return
    store = entry.runtime_data.store
    summary = store.get(msg["workout_id"])
    detail = await store.async_get_detail(msg["workout_id"]) if summary else None
    if detail and not connection.user.is_admin:
        # Administratoren bekommen die ganze Route (eigener Export, z. B. fuer
        # eine andere App), freigegebene Konten nur den Teil ausserhalb der Zone
        detail = _zone(hass, entry, detail)
    text = (
        await hass.async_add_executor_job(build_gpx, summary, detail)
        if detail
        else None
    )
    if text is None:
        connection.send_error(msg["id"], "not_found", "Keine Route zu diesem Training")
        return
    connection.send_result(msg["id"], {"filename": filename(summary), "gpx": text})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/delete_workout",
        vol.Required("workout_id"): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Training loeschen (wie der Dienst ha_training.delete_workout)."""
    from homeassistant.exceptions import ServiceValidationError

    from .services import async_delete_workout

    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Kein Eintrag geladen")
        return
    try:
        await async_delete_workout(hass, entry, msg["workout_id"])
    except ServiceValidationError:
        connection.send_error(msg["id"], "not_found", "Training nicht gefunden")
        return
    connection.send_result(msg["id"], {"deleted": msg["workout_id"]})
