"""Einrichtung: erzeugt die geheime Webhook-Adresse und zeigt sie an."""

from __future__ import annotations

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


class TrainingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ein Eintrag je Home Assistant; mehrere Uhren schicken an denselben."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(step_id="user")
        webhook_id = webhook.async_generate_id()
        return self.async_create_entry(
            title=TITLE,
            data={CONF_WEBHOOK_ID: webhook_id},
            description_placeholders={"url": webhook_url(self.hass, webhook_id)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TrainingOptionsFlow()


class TrainingOptionsFlow(OptionsFlow):
    """Zeigt die Webhook-Adresse erneut und stellt die Aufbewahrung ein."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_KEEP_DETAILS: int(user_input[CONF_KEEP_DETAILS])}
            )
        keep = self.config_entry.options.get(CONF_KEEP_DETAILS, DEFAULT_KEEP_DETAILS)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_KEEP_DETAILS, default=keep): (
                        selector.NumberSelector(
                            selector.NumberSelectorConfig(
                                min=MIN_KEEP_DETAILS,
                                max=MAX_KEEP_DETAILS,
                                step=10,
                                mode=selector.NumberSelectorMode.BOX,
                            )
                        )
                    )
                }
            ),
            description_placeholders={
                "url": webhook_url(self.hass, self.config_entry.data[CONF_WEBHOOK_ID])
            },
        )
