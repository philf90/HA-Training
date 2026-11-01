"""Wer Route, Verlaeufe und GPX sieht: Administratoren und freigegebene Konten."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ha_training.const import (
    CONF_KEEP_DETAILS,
    CONF_REQUIRE_TOKEN,
    CONF_ROUTE_USERS,
)

from .conftest import payload, post, workout


async def _ask(ws, msg_id, kind):
    await ws.send_json({"id": msg_id, "type": kind, "workout_id": "TEST-0001"})
    return await ws.receive_json()


async def test_guest_sees_summary_but_no_route(
    hass: HomeAssistant, entry, hass_client, hass_ws_client, hass_read_only_access_token
):
    await post(hass_client, payload(workout()))
    guest = await hass_ws_client(hass, hass_read_only_access_token)

    msg = await _ask(guest, 1, "ha_training/workout")
    assert msg["success"]
    assert msg["result"]["summary"]["distance_km"] == 2.5
    assert msg["result"]["detail"] is None
    assert msg["result"]["detail_hidden"] is True

    msg = await _ask(guest, 2, "ha_training/gpx")
    assert msg["error"]["code"] == "unauthorized"

    # Die Liste (Zusammenfassungen) bleibt sichtbar
    await guest.send_json({"id": 3, "type": "ha_training/workouts"})
    msg = await guest.receive_json()
    assert [w["id"] for w in msg["result"]["workouts"]] == ["TEST-0001"]


async def test_admin_sees_route(
    hass: HomeAssistant, entry, hass_client, hass_ws_client
):
    await post(hass_client, payload(workout()))
    admin = await hass_ws_client(hass)
    msg = await _ask(admin, 1, "ha_training/workout")
    assert msg["result"]["detail"]["route"]
    assert "detail_hidden" not in msg["result"]
    msg = await _ask(admin, 2, "ha_training/gpx")
    assert msg["success"]


async def test_shared_account_sees_route(
    hass: HomeAssistant,
    entry,
    hass_client,
    hass_ws_client,
    hass_read_only_user,
    hass_read_only_access_token,
    hass_admin_user,
):
    await post(hass_client, payload(workout()))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    field = next(k for k in schema if k == CONF_ROUTE_USERS)
    options = schema[field].config["options"]
    # Angeboten werden nur Konten ohne Adminrechte, hier das Lesekonto
    offered = [o["value"] for o in options]
    assert hass_read_only_user.id in offered
    assert hass_admin_user.id not in offered
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_KEEP_DETAILS: 200,
            CONF_REQUIRE_TOKEN: False,
            CONF_ROUTE_USERS: [hass_read_only_user.id],
        },
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_ROUTE_USERS] == [hass_read_only_user.id]

    guest = await hass_ws_client(hass, hass_read_only_access_token)
    msg = await _ask(guest, 1, "ha_training/workout")
    assert msg["result"]["detail"]["route"]
    msg = await _ask(guest, 2, "ha_training/gpx")
    assert msg["success"]


async def test_unknown_account_ids_are_dropped(
    hass: HomeAssistant, entry, hass_read_only_user
):
    # Alte Optionen mit einer ID, die es nicht mehr gibt, und einer gueltigen
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_ROUTE_USERS: ["gibt-es-nicht", hass_read_only_user.id],
        },
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    field = next(k for k in schema if k == CONF_ROUTE_USERS)
    assert field.default() == [hass_read_only_user.id]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_KEEP_DETAILS: 200,
            CONF_REQUIRE_TOKEN: False,
            CONF_ROUTE_USERS: [hass_read_only_user.id],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ROUTE_USERS] == [hass_read_only_user.id]


async def test_no_field_without_other_accounts(hass: HomeAssistant, entry):
    # Nur Administratoren vorhanden: kein Auswahlfeld, Optionen ohne Konten
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert CONF_ROUTE_USERS not in [str(k) for k in result["data_schema"].schema]
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_KEEP_DETAILS: 200, CONF_REQUIRE_TOKEN: False}
    )
    assert entry.options[CONF_ROUTE_USERS] == []
