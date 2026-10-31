"""Keine echten Orte im Repo, keine Webhook-ID im Log.

Die Route zeigt Wohnort und Wege. Im Repo duerfen Koordinaten nur aus dem
erfundenen Kreis der Tests stammen (conftest.CENTER); alles andere schlaegt
hier fehl, bevor es veroeffentlicht wird.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from homeassistant.core import HomeAssistant

from .conftest import CENTER, WEBHOOK_ID, payload, post, workout

ROOT = Path(__file__).parents[1]
SKIP_DIRS = {".git", "leaflet", "__pycache__", ".pytest_cache", ".ruff_cache"}
TEXT_SUFFIXES = {".py", ".js", ".json", ".md", ".yml", ".yaml", ".txt", ".ini", ""}
# Zwei Kommazahlen mit mindestens vier Nachkommastellen nebeneinander
PAIR = re.compile(r"(-?\d{1,3}\.\d{4,})\s*[,;/ ]\s*(-?\d{1,3}\.\d{4,})")


def _files():
    for path in ROOT.rglob("*"):
        if (
            path.is_file()
            and not SKIP_DIRS.intersection(path.parts)
            and path.suffix in TEXT_SUFFIXES
        ):
            yield path


def test_no_real_coordinates_in_repo():
    found = []
    for path in _files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in PAIR.finditer(text):
            lat, lon = float(match.group(1)), float(match.group(2))
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            if abs(lat - CENTER[0]) < 0.05 and abs(lon - CENTER[1]) < 0.05:
                continue
            found.append(f"{path.relative_to(ROOT)}: {match.group(0)}")
    assert not found, "Koordinaten ausserhalb des Testkreises:\n" + "\n".join(found)


def test_no_export_files_in_repo():
    """Exporte von Health Auto Export gehoeren nicht ins Repo."""
    names = [
        p.name
        for p in ROOT.rglob("*")
        if not SKIP_DIRS.intersection(p.parts)
        and (p.suffix in (".gpx", ".zip") or p.name.startswith("HealthAutoExport"))
    ]
    assert names == []


async def test_webhook_id_not_logged(hass: HomeAssistant, entry, hass_client, caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.ha_training")
    await post(hass_client, payload(workout()))
    integration_logs = [
        r.getMessage() for r in caplog.records if r.name.startswith("custom_components")
    ]
    assert integration_logs, "die Integration hat nichts protokolliert"
    assert not any(WEBHOOK_ID in line for line in integration_logs)
