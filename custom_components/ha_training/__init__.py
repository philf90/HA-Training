"""Training: Trainings der Apple Watch aus Health Auto Export.

Health Auto Export (iOS) schickt Trainings samt GPS-Route und Pulsverlauf per
REST-Automation an einen Webhook dieser Integration. Gespeichert wird privat
unter .storage/; Sensoren und eine Ereignis-Entitaet zeigen das letzte Training
und die Woche, die mitgelieferte Karte holt Route und Verlaeufe ueber die
WebSocket-API (nur fuer angemeldete Nutzer).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import (
    CARD,
    CARD_PATH,
    CONF_KEEP_DETAILS,
    CONF_WEBHOOK_ID,
    DEFAULT_KEEP_DETAILS,
    DOMAIN,
    LEAFLET_DIR,
    SIGNAL_UPDATED,
    TITLE,
)
from .parser import parse_payload
from .storage import TrainingStore
from .websocket import async_register_websocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.EVENT, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
CARD_DIR = Path(__file__).parent / "frontend"


@dataclass
class TrainingData:
    """Laufzeitdaten eines Eintrags."""

    store: TrainingStore


type TrainingConfigEntry = ConfigEntry[TrainingData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await _async_register_card(hass)
    async_register_websocket(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Karte und Leaflet ausliefern und die Karte im Frontend laden.

    Die Version im Pfad sorgt dafuer, dass der Browser nach einem Update die
    neue Datei laedt. Die Dateien enthalten keine Trainingsdaten; die holt die
    Karte erst ueber die WebSocket-API.
    """
    if getattr(hass, "http", None) is None:
        return
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(f"{CARD_PATH}/{CARD}", str(CARD_DIR / CARD), True),
            StaticPathConfig(
                f"{CARD_PATH}/{LEAFLET_DIR}", str(CARD_DIR / LEAFLET_DIR), True
            ),
        ]
    )
    if "frontend" not in hass.config.components:
        return
    from homeassistant.components.frontend import add_extra_js_url

    integration = await async_get_integration(hass, DOMAIN)
    add_extra_js_url(hass, f"{CARD_PATH}/{CARD}?v={integration.version}")


async def async_setup_entry(hass: HomeAssistant, entry: TrainingConfigEntry) -> bool:
    store = TrainingStore(
        hass,
        entry.entry_id,
        entry.options.get(CONF_KEEP_DETAILS, DEFAULT_KEEP_DETAILS),
    )
    await store.async_load()
    entry.runtime_data = TrainingData(store)

    async def handle_webhook(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        return await _async_handle_webhook(hass, entry, request)

    webhook.async_register(
        hass,
        DOMAIN,
        TITLE,
        entry.data[CONF_WEBHOOK_ID],
        handle_webhook,
        # Health Auto Export sendet auch von unterwegs, also ueber die externe
        # Adresse; geschuetzt ist der Webhook durch seine geheime ID.
        local_only=False,
        allowed_methods=["POST"],
    )
    entry.async_on_unload(
        lambda: webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
    )
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_handle_webhook(
    hass: HomeAssistant, entry: TrainingConfigEntry, request: web.Request
) -> web.Response:
    """REST-Aufruf von Health Auto Export annehmen."""
    try:
        payload = await request.json()
    except ValueError:
        return web.json_response({"fehler": "kein JSON"}, status=400)
    parsed, rejected = parse_payload(payload)
    store = entry.runtime_data.store
    new, updated = await store.async_add(parsed)
    if new or updated:
        async_dispatcher_send(hass, f"{SIGNAL_UPDATED}_{entry.entry_id}", new)
    _LOGGER.debug(
        "Webhook: %s Trainings, %s neu, %s geaendert, %s verworfen",
        len(parsed),
        len(new),
        updated,
        rejected,
    )
    return web.json_response(
        {
            "trainings": len(parsed),
            "neu": len(new),
            "geaendert": updated,
            "verworfen": rejected,
        }
    )


async def _async_options_updated(
    hass: HomeAssistant, entry: TrainingConfigEntry
) -> None:
    keep = entry.options.get(CONF_KEEP_DETAILS, DEFAULT_KEEP_DETAILS)
    await entry.runtime_data.store.async_set_keep_details(keep)


async def async_unload_entry(hass: HomeAssistant, entry: TrainingConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Beim Entfernen alle gespeicherten Trainings loeschen."""
    await TrainingStore(hass, entry.entry_id, 0).async_remove_all()
