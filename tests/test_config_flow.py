"""Einrichtung und Optionen."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_training.const import (
    CONF_KEEP_DETAILS,
    CONF_WEBHOOK_ID,
    DOMAIN,
)

from .conftest import WEBHOOK_ID, payload, post, workout


async def test_user_flow_creates_secret_webhook(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    webhook_id = result["data"][CONF_WEBHOOK_ID]
    assert len(webhook_id) >= 32
    assert result["description_placeholders"]["url"].endswith(
        f"/api/webhook/{webhook_id}"
    )


async def test_only_one_entry(hass: HomeAssistant, entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] in ("already_configured", "single_instance_allowed")


async def test_options_show_url_and_prune(hass: HomeAssistant, entry, hass_client):
    from datetime import datetime, timedelta, timezone

    start = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    workouts = [
        workout(f"W{i:02d}", start + timedelta(days=i), minutes=5, pause=None)
        for i in range(12)
    ]
    await post(hass_client, payload(*workouts))
    store = entry.runtime_data.store
    assert all(w["has_detail"] for w in store.workouts)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"]["url"].endswith(WEBHOOK_ID)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_KEEP_DETAILS: 10}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert store.keep_details == 10
    kept = [w["id"] for w in store.workouts if w["has_detail"]]
    assert len(kept) == 10
    # Neueste zuerst; die beiden aeltesten verlieren ihre Details
    assert store.workouts[-1]["id"] == "W00"
    assert not store.workouts[-1]["has_detail"]
    assert await store.async_get_detail("W00") is None
    assert (await store.async_get_detail("W11"))["route"]
