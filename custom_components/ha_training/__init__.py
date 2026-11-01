"""Training: Trainings der Apple Watch aus Health Auto Export.

Health Auto Export (iOS) schickt Trainings samt GPS-Route und Pulsverlauf per
REST-Automation an einen Webhook dieser Integration. Gespeichert wird privat
unter .storage/; Sensoren und eine Ereignis-Entitaet zeigen das letzte Training
und die Woche, die mitgelieferte Karte holt Route und Verlaeufe ueber die
WebSocket-API (nur fuer angemeldete Nutzer).
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from pathlib import Path

from aiohttp import hdrs, web
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
    CONF_REQUIRE_TOKEN,
    CONF_TOKEN,
    CONF_WEBHOOK_ID,
    DEFAULT_KEEP_DETAILS,
    DOMAIN,
    LEAFLET_DIR,
    SIGNAL_UPDATED,
    TITLE,
)
from .parser import PayloadError, decode_and_parse
from .services import async_register_services
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
    async_register_services(hass)
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


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """1.1 -> 1.2: Token anlegen. Er ist aus, damit Health Auto Export weiter
    ohne Header senden kann, bis man ihn dort eingetragen und hier eingeschaltet
    hat."""
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        from .config_flow import generate_token

        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_TOKEN: generate_token()},
            options={**entry.options, CONF_REQUIRE_TOKEN: False},
            minor_version=2,
        )
        _LOGGER.info("Training: Token angelegt, Token-Pflicht aus (Konfigurieren)")
    return True


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

    # Die ID beim Anmelden festhalten: Nach "Neu konfigurieren" steht in
    # entry.data schon die neue, abgemeldet werden muss aber die alte.
    webhook_id = entry.data[CONF_WEBHOOK_ID]
    webhook.async_register(
        hass,
        DOMAIN,
        TITLE,
        webhook_id,
        handle_webhook,
        # Health Auto Export sendet auch von unterwegs, also ueber die externe
        # Adresse; geschuetzt ist der Webhook durch seine geheime ID.
        local_only=False,
        allowed_methods=["POST"],
    )
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_handle_webhook(
    hass: HomeAssistant, entry: TrainingConfigEntry, request: web.Request
) -> web.Response:
    """REST-Aufruf von Health Auto Export annehmen."""
    # Vor dem Lesen des Inhalts: Ohne Token wird nichts geparst
    if not _token_ok(entry, request):
        _LOGGER.warning("Webhook: Aufruf ohne gueltigen Token abgelehnt")
        return web.json_response(
            {"fehler": "token fehlt oder falsch"},
            status=401,
            headers={hdrs.WWW_AUTHENTICATE: "Bearer"},
        )
    body = await request.read()
    try:
        # JSON und Parser kosten bei grossen Exporten Rechenzeit: nicht im
        # Event-Loop, sonst steht Home Assistant so lange
        parsed, rejected = await hass.async_add_executor_job(decode_and_parse, body)
    except PayloadError as err:
        if err.limit is not None:
            return web.json_response(
                {"fehler": err.code, "maximal": err.limit}, status=413
            )
        return web.json_response({"fehler": err.code}, status=400)
    store = entry.runtime_data.store
    new, updated, skipped = await store.async_add(parsed)
    if new or updated:
        async_dispatcher_send(hass, f"{SIGNAL_UPDATED}_{entry.entry_id}", new)
    _LOGGER.debug(
        "Webhook: %s Trainings, %s neu, %s geaendert, %s verworfen, %s geloescht",
        len(parsed),
        len(new),
        updated,
        rejected,
        skipped,
    )
    return web.json_response(
        {
            "trainings": len(parsed),
            "neu": len(new),
            "geaendert": updated,
            "verworfen": rejected,
            # Schon einmal geloescht und deshalb nicht wieder angelegt
            "geloescht": skipped,
        }
    )


def _token_ok(entry: TrainingConfigEntry, request: web.Request) -> bool:
    """Header "Authorization: Bearer <token>" pruefen, wenn er verlangt ist.

    Home Assistant wertet denselben Header als eigenes Zugangstoken aus; ein
    fremder Wert macht die Anfrage nur "nicht angemeldet", was der Webhook
    nicht braucht (keine Sperre, kein Fehlversuch).
    """
    if not entry.options.get(CONF_REQUIRE_TOKEN, False):
        return True
    scheme, _, given = request.headers.get(hdrs.AUTHORIZATION, "").partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(
        given.strip().encode("utf-8", "replace"),
        entry.data[CONF_TOKEN].encode("utf-8"),
    )


async def _async_options_updated(
    hass: HomeAssistant, entry: TrainingConfigEntry
) -> None:
    keep = entry.options.get(CONF_KEEP_DETAILS, DEFAULT_KEEP_DETAILS)
    await entry.runtime_data.store.async_set_keep_details(keep)
    # Sensoren neu schreiben: die Karte sieht am Zaehler "revision", dass sie
    # neu laden muss (Aufbewahrung oder Freigabe der Routen geaendert)
    async_dispatcher_send(hass, f"{SIGNAL_UPDATED}_{entry.entry_id}", [])


async def async_unload_entry(hass: HomeAssistant, entry: TrainingConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Beim Entfernen alle gespeicherten Trainings loeschen."""
    await TrainingStore(hass, entry.entry_id, 0).async_remove_all()
