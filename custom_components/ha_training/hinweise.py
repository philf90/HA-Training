"""Hinweise unter "Reparaturen", wenn der Webhook Uebertragungen ablehnt (V6).

Die Fehlermeldung des Webhooks geht nur an Health Auto Export zurueck; in Home
Assistant fiele eine falsche Einstellung sonst erst auf, wenn neue Trainings
ausbleiben. Nur Faelle, die sich in der App beheben lassen (Regel
"repair-issues" der Quality Scale: "When something is wrong that the user can
fix, the integration raises a repair issue."):

- unauthorized: Token fehlt oder ist falsch (HTTP 401)
- invalid_json: Inhalt ist kein JSON (HTTP 400)
- too_many_workouts: mehr Trainings in einem Aufruf als erlaubt (HTTP 413)

Der Hinweis zaehlt die Ablehnungen und nennt die letzte; er bleibt ueber einen
Neustart (is_persistent) und verschwindet mit der naechsten angenommenen
Uebertragung. Er enthaelt weder Webhook-Adresse noch Token noch Inhalte.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import DOMAIN

# Fehlercode des Webhooks -> (Hinweis, Abschnitt im README)
ISSUES = {
    "unauthorized": ("webhook_unauthorized", "webhook-mit-token-absichern"),
    "invalid_json": ("webhook_invalid_json", "health-auto-export-einstellen"),
    "too_many_workouts": ("webhook_too_many", "health-auto-export-einstellen"),
}
README = "https://github.com/philf90/HA-Training#"


@callback
def async_rejected(hass: HomeAssistant, error: str, limit: int | None = None) -> None:
    """Ablehnung melden: Hinweis anlegen oder Zaehler erhoehen."""
    if error not in ISSUES:
        return
    issue_id, anchor = ISSUES[error]
    old = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    count = 1
    if old is not None and old.translation_placeholders:
        try:
            count = int(old.translation_placeholders.get("count", "0")) + 1
        except ValueError:
            count = 1
    placeholders = {
        "count": str(count),
        "last": dt_util.now().strftime("%Y-%m-%d %H:%M"),
    }
    if limit is not None:
        placeholders["limit"] = str(limit)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=True,
        learn_more_url=README + anchor,
        severity=ir.IssueSeverity.ERROR,
        translation_key=issue_id,
        translation_placeholders=placeholders,
    )


@callback
def async_accepted(hass: HomeAssistant) -> None:
    """Uebertragung angenommen: alle Hinweise des Webhooks entfernen."""
    for issue_id, _anchor in ISSUES.values():
        ir.async_delete_issue(hass, DOMAIN, issue_id)
