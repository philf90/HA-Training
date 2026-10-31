"""Entitaets-IDs einer deutschen Instanz stimmen mit dem README ueberein."""

from __future__ import annotations

import re
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_training.const import CONF_WEBHOOK_ID, DOMAIN

README = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")


async def test_german_entity_ids_match_readme(hass: HomeAssistant):
    hass.config.language = "de"
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_WEBHOOK_ID: "x"})
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    ids = {
        e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    documented = set(re.findall(r"`((?:sensor|event)\.training_[a-z_]+)`", README))
    assert ids == documented
