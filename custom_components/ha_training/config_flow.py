"""Einrichtung: erzeugt die geheime Webhook-Adresse und den Token und zeigt sie an.

"Konfigurieren" zeigt Adresse und Token erneut und stellt Aufbewahrung und
Token-Pflicht ein; "Neu konfigurieren" erzeugt eine neue Adresse oder einen
neuen Token, ohne die gespeicherten Trainings anzutasten.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components import webhook
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.network import NoURLAvailableError

from .const import (
    CONF_KEEP_DETAILS,
    CONF_NEW_TOKEN,
    CONF_NEW_WEBHOOK,
    CONF_REQUIRE_TOKEN,
    CONF_ROUTE_USERS,
    CONF_TOKEN,
    CONF_WEBHOOK_ID,
    DEFAULT_KEEP_DETAILS,
    DOMAIN,
    MAX_KEEP_DETAILS,
    MIN_KEEP_DETAILS,
    TITLE,
)


def webhook_url(hass: HomeAssistant, webhook_id: str) -> str:
    """Externe Adresse bevorzugt; ohne eingestellte Adresse nur der Pfad."""
    try:
        return webhook.async_generate_url(hass, webhook_id)
    except NoURLAvailableError:
        return webhook.async_generate_path(webhook_id)


def generate_token() -> str:
    """256 Bit, URL-sicher (Buchstaben, Ziffern, - und _), ohne Leerzeichen."""
    return secrets.token_urlsafe(32)


def placeholders(hass: HomeAssistant, data: Mapping[str, Any]) -> dict[str, str]:
    """Adresse und fertiger Header-Wert fuer die Texte der Dialoge."""
    return {
        "url": webhook_url(hass, data[CONF_WEBHOOK_ID]),
        "header": f"Bearer {data[CONF_TOKEN]}",
    }


class TrainingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ein Eintrag je Home Assistant; mehrere Uhren schicken an denselben."""

    VERSION = 1
    # 1.2: Token in data, Option require_token (Migration in __init__.py)
    MINOR_VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(step_id="user")
        data = {
            CONF_WEBHOOK_ID: webhook.async_generate_id(),
            CONF_TOKEN: generate_token(),
        }
        return self.async_create_entry(
            title=TITLE,
            data=data,
            options={
                CONF_KEEP_DETAILS: DEFAULT_KEEP_DETAILS,
                CONF_REQUIRE_TOKEN: True,
            },
            description_placeholders=placeholders(self.hass, data),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Neue Webhook-Adresse und/oder neuen Token erzeugen; Trainings bleiben."""
        entry = self._get_reconfigure_entry()
        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_NEW_WEBHOOK, default=False
                        ): selector.BooleanSelector(),
                        vol.Required(
                            CONF_NEW_TOKEN, default=False
                        ): selector.BooleanSelector(),
                    }
                ),
            )
        data = dict(entry.data)
        if user_input[CONF_NEW_WEBHOOK]:
            data[CONF_WEBHOOK_ID] = webhook.async_generate_id()
        if user_input[CONF_NEW_TOKEN]:
            data[CONF_TOKEN] = generate_token()
        if data == dict(entry.data):
            return self.async_abort(reason="reconfigure_unchanged")
        self.hass.config_entries.async_update_entry(entry, data=data)
        # Neu laden meldet den Webhook unter der neuen ID an und die alte ab
        self.hass.config_entries.async_schedule_reload(entry.entry_id)
        return self.async_abort(
            reason="reconfigure_successful",
            description_placeholders=placeholders(self.hass, data),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TrainingOptionsFlow()


async def other_users(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Aktive Konten ohne Administratorrechte (die sehen Routen ohnehin)."""
    users = await hass.auth.async_get_users()
    return sorted(
        (
            selector.SelectOptionDict(value=u.id, label=u.name or u.id)
            for u in users
            if u.is_active and not u.system_generated and not u.is_admin
        ),
        key=lambda option: option["label"].lower(),
    )


class TrainingOptionsFlow(OptionsFlow):
    """Zeigt Adresse und Token erneut, stellt Aufbewahrung, Token-Pflicht und
    die Konten ein, die Routen sehen duerfen."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = self.config_entry.options
        users = await other_users(self.hass)
        if user_input is not None:
            known = {u["value"] for u in users}
            return self.async_create_entry(
                data={
                    CONF_KEEP_DETAILS: int(user_input[CONF_KEEP_DETAILS]),
                    CONF_REQUIRE_TOKEN: bool(user_input[CONF_REQUIRE_TOKEN]),
                    # Ohne Auswahlfeld (kein anderes Konto) bleibt es leer;
                    # geloeschte oder inzwischen zu Admins gemachte Konten fallen raus
                    CONF_ROUTE_USERS: [
                        u for u in user_input.get(CONF_ROUTE_USERS, []) if u in known
                    ],
                }
            )
        keep = options.get(CONF_KEEP_DETAILS, DEFAULT_KEEP_DETAILS)
        require = options.get(CONF_REQUIRE_TOKEN, False)
        schema: dict[Any, Any] = {
            vol.Required(CONF_KEEP_DETAILS, default=keep): (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_KEEP_DETAILS,
                        max=MAX_KEEP_DETAILS,
                        step=10,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            ),
            vol.Required(
                CONF_REQUIRE_TOKEN, default=require
            ): selector.BooleanSelector(),
        }
        if users:
            known = {u["value"] for u in users}
            chosen = [u for u in options.get(CONF_ROUTE_USERS, []) if u in known]
            schema[vol.Optional(CONF_ROUTE_USERS, default=chosen)] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=users,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            description_placeholders=placeholders(self.hass, self.config_entry.data),
        )
