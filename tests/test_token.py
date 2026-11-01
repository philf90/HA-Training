"""Token im Header, Migration von 0.1.4 und "Neu konfigurieren"."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_training.const import (
    CONF_KEEP_DETAILS,
    CONF_NEW_TOKEN,
    CONF_NEW_WEBHOOK,
    CONF_REQUIRE_TOKEN,
    CONF_TOKEN,
    CONF_WEBHOOK_ID,
    DOMAIN,
)
from custom_components.ha_training.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import WEBHOOK_ID, payload, workout

TOKEN = "test-token-geheim"


@pytest.fixture
async def token_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Eintrag wie nach einer Neueinrichtung mit 0.1.5: Token verlangt."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Training",
        version=1,
        minor_version=2,
        data={CONF_WEBHOOK_ID: WEBHOOK_ID, CONF_TOKEN: TOKEN},
        options={CONF_REQUIRE_TOKEN: True},
    )
    config_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return config_entry


async def send(hass_client_no_auth, header: str | None, webhook_id: str = WEBHOOK_ID):
    client = await hass_client_no_auth()
    headers = {"Authorization": header} if header is not None else {}
    return await client.post(
        f"/api/webhook/{webhook_id}", json=payload(workout()), headers=headers
    )


async def test_new_entry_has_token_and_requires_it(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    token = result["data"][CONF_TOKEN]
    assert len(token) >= 40
    assert token != result["data"][CONF_WEBHOOK_ID]
    assert result["options"][CONF_REQUIRE_TOKEN] is True
    assert result["description_placeholders"]["header"] == f"Bearer {token}"
    assert result["result"].minor_version == 2


async def test_migration_from_0_1_4_keeps_webhook_open(
    hass: HomeAssistant, entry, hass_client_no_auth
):
    # Der Eintrag aus conftest hat wie unter 0.1.4 keinen Token
    assert entry.minor_version == 2
    assert len(entry.data[CONF_TOKEN]) >= 40
    assert entry.data[CONF_WEBHOOK_ID] == WEBHOOK_ID
    assert entry.options[CONF_REQUIRE_TOKEN] is False
    response = await send(hass_client_no_auth, None)
    assert (await response.json())["neu"] == 1


@pytest.mark.parametrize(
    "header",
    [None, "Bearer falsch", f"Basic {TOKEN}", TOKEN, f"Bearer {TOKEN}x", "Bearer "],
)
async def test_without_valid_token_rejected(
    hass: HomeAssistant, token_entry, hass_client_no_auth, header
):
    with patch("custom_components.ha_training.parse_payload") as parse:
        response = await send(hass_client_no_auth, header)
    assert response.status == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    # Abgelehnt, bevor der Inhalt gelesen wird
    parse.assert_not_called()
    assert token_entry.runtime_data.store.workouts == []


@pytest.mark.parametrize("header", [f"Bearer {TOKEN}", f"bearer {TOKEN}"])
async def test_valid_token_accepted(
    hass: HomeAssistant, token_entry, hass_client_no_auth, header
):
    response = await send(hass_client_no_auth, header)
    assert response.status == 200
    assert (await response.json())["neu"] == 1


async def test_option_switches_token_without_reload(
    hass: HomeAssistant, entry, hass_client_no_auth
):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    header = result["description_placeholders"]["header"]
    assert header == f"Bearer {entry.data[CONF_TOKEN]}"
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_KEEP_DETAILS: 200, CONF_REQUIRE_TOKEN: True}
    )
    await hass.async_block_till_done()
    assert entry.options == {CONF_KEEP_DETAILS: 200, CONF_REQUIRE_TOKEN: True}
    assert (await send(hass_client_no_auth, None)).status == 401
    assert (await send(hass_client_no_auth, header)).status == 200


async def _reconfigure(hass: HomeAssistant, entry, user_input):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()
    return result


async def test_reconfigure_new_webhook_keeps_workouts(
    hass: HomeAssistant, token_entry, hass_client_no_auth
):
    await send(hass_client_no_auth, f"Bearer {TOKEN}")
    result = await _reconfigure(
        hass, token_entry, {CONF_NEW_WEBHOOK: True, CONF_NEW_TOKEN: False}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    new_id = token_entry.data[CONF_WEBHOOK_ID]
    assert new_id != WEBHOOK_ID
    assert token_entry.data[CONF_TOKEN] == TOKEN
    assert result["description_placeholders"]["url"].endswith(new_id)
    assert result["description_placeholders"]["header"] == f"Bearer {TOKEN}"
    # Die Trainings sind noch da
    store = token_entry.runtime_data.store
    assert [w["id"] for w in store.workouts] == ["TEST-0001"]
    # Alte Adresse: Home Assistant antwortet bei unbekannten Webhooks mit 200,
    # verarbeitet wird aber nichts mehr
    second = workout("TEST-0002")
    client = await hass_client_no_auth()
    old = await client.post(
        f"/api/webhook/{WEBHOOK_ID}",
        json=payload(second),
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert await old.text() == ""
    assert len(store.workouts) == 1
    new = await client.post(
        f"/api/webhook/{new_id}",
        json=payload(second),
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert (await new.json())["neu"] == 1


async def test_reconfigure_new_token(
    hass: HomeAssistant, token_entry, hass_client_no_auth
):
    result = await _reconfigure(
        hass, token_entry, {CONF_NEW_WEBHOOK: False, CONF_NEW_TOKEN: True}
    )
    assert result["reason"] == "reconfigure_successful"
    token = token_entry.data[CONF_TOKEN]
    assert token != TOKEN
    assert token_entry.data[CONF_WEBHOOK_ID] == WEBHOOK_ID
    assert result["description_placeholders"]["header"] == f"Bearer {token}"
    assert (await send(hass_client_no_auth, f"Bearer {TOKEN}")).status == 401
    assert (await send(hass_client_no_auth, f"Bearer {token}")).status == 200


async def test_reconfigure_nothing_selected(hass: HomeAssistant, token_entry):
    before = dict(token_entry.data)
    result = await _reconfigure(
        hass, token_entry, {CONF_NEW_WEBHOOK: False, CONF_NEW_TOKEN: False}
    )
    assert result["reason"] == "reconfigure_unchanged"
    assert dict(token_entry.data) == before


async def test_token_not_in_diagnostics_or_log(
    hass: HomeAssistant, token_entry, hass_client_no_auth, caplog
):
    await send(hass_client_no_auth, f"Bearer {TOKEN}")
    await send(hass_client_no_auth, "Bearer falsch")
    diag = await async_get_config_entry_diagnostics(hass, token_entry)
    assert diag["entry"]["data"][CONF_TOKEN] == "**REDACTED**"
    assert TOKEN not in str(diag)
    assert TOKEN not in caplog.text
    assert "ohne gueltigen Token abgelehnt" in caplog.text


async def test_wrong_token_does_not_ban_ip(hass: HomeAssistant, hass_client_no_auth):
    # Sperre nach dem ersten Fehlversuch: ein falscher Token darf nicht zaehlen
    assert await async_setup_component(
        hass, "http", {"http": {"ip_ban_enabled": True, "login_attempts_threshold": 1}}
    )
    await hass.config.async_set_time_zone("Europe/Berlin")
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=2,
        data={CONF_WEBHOOK_ID: WEBHOOK_ID, CONF_TOKEN: TOKEN},
        options={CONF_REQUIRE_TOKEN: True},
    )
    config_entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    for _ in range(3):
        assert (await send(hass_client_no_auth, "Bearer falsch")).status == 401
    assert (await send(hass_client_no_auth, f"Bearer {TOKEN}")).status == 200
