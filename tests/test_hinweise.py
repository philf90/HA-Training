"""0.1.24 (V6): Hinweise unter "Reparaturen", wenn der Webhook ablehnt."""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.ha_training.const import DOMAIN
from custom_components.ha_training.parser import MAX_WORKOUTS_PER_CALL

from .conftest import WEBHOOK_ID, payload, post, workout
from .test_token import TOKEN, send, token_entry  # noqa: F401 (Fixture)


def _issue(hass: HomeAssistant, issue_id: str) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


@pytest.mark.usefixtures("token_entry")
async def test_wrong_token_raises_issue_and_counts(
    hass: HomeAssistant, hass_client_no_auth
):
    assert (await send(hass_client_no_auth, "Bearer falsch")).status == 401
    issue = _issue(hass, "webhook_unauthorized")
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.is_persistent and not issue.is_fixable
    assert issue.translation_key == "webhook_unauthorized"
    assert issue.translation_placeholders["count"] == "1"
    assert issue.learn_more_url.endswith("#webhook-mit-token-absichern")
    await send(hass_client_no_auth, None)
    assert _issue(hass, "webhook_unauthorized").translation_placeholders["count"] == "2"
    # Kein Geheimnis im Hinweis
    text = json.dumps(_issue(hass, "webhook_unauthorized").to_json())
    assert WEBHOOK_ID not in text and TOKEN not in text and "falsch" not in text


@pytest.mark.usefixtures("token_entry")
async def test_accepted_upload_clears_issue(hass: HomeAssistant, hass_client_no_auth):
    await send(hass_client_no_auth, None)
    assert _issue(hass, "webhook_unauthorized") is not None
    assert (await send(hass_client_no_auth, f"Bearer {TOKEN}")).status == 200
    assert _issue(hass, "webhook_unauthorized") is None


async def test_invalid_json(hass: HomeAssistant, entry, hass_client):
    response = await post(hass_client, b"kein json {", raw=True)
    assert response.status == 400
    issue = _issue(hass, "webhook_invalid_json")
    assert issue is not None and issue.translation_placeholders["count"] == "1"
    assert issue.learn_more_url.endswith("#health-auto-export-einstellen")
    # Angenommen: weg
    await post(hass_client, payload(workout()))
    assert _issue(hass, "webhook_invalid_json") is None


async def test_too_many_workouts(hass: HomeAssistant, entry, hass_client):
    many = [{"id": f"W{i}"} for i in range(MAX_WORKOUTS_PER_CALL + 1)]
    response = await post(hass_client, payload(*many))
    assert response.status == 413
    issue = _issue(hass, "webhook_too_many")
    assert issue is not None
    assert issue.translation_placeholders["limit"] == str(MAX_WORKOUTS_PER_CALL)


async def test_accepted_clears_all_three(hass: HomeAssistant, entry, hass_client):
    await post(hass_client, b"x", raw=True)
    await post(hass_client, payload(*[{"id": f"W{i}"} for i in range(1001)]))
    for issue_id in ("webhook_invalid_json", "webhook_too_many"):
        assert _issue(hass, issue_id) is not None
    # Auch ein Aufruf ohne Trainings ist angenommen
    assert (await post(hass_client, payload())).status == 200
    for issue_id in ("webhook_invalid_json", "webhook_too_many"):
        assert _issue(hass, issue_id) is None


async def test_count_continues_after_restart(hass: HomeAssistant, entry, hass_client):
    await post(hass_client, b"x", raw=True)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await post(hass_client, b"x", raw=True)
    assert _issue(hass, "webhook_invalid_json").translation_placeholders["count"] == "2"


async def test_translations_have_all_placeholders():
    from pathlib import Path

    root = Path(__file__).parent.parent / "custom_components" / "ha_training"
    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        issues = json.loads((root / name).read_text(encoding="utf-8"))["issues"]
        for issue_id in (
            "webhook_unauthorized",
            "webhook_invalid_json",
            "webhook_too_many",
        ):
            text = issues[issue_id]["description"]
            assert "{count}" in text and "{last}" in text, (name, issue_id)
        assert "{limit}" in issues["webhook_too_many"]["description"]
