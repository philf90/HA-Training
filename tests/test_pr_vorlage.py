"""Tests fuer die Pruefung der PR-Vorlage (.github/scripts/pruefe_pr.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
_spec = importlib.util.spec_from_file_location(
    "pruefe_pr", ROOT / ".github" / "scripts" / "pruefe_pr.py"
)
pruefe_pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pruefe_pr)

TEMPLATE = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")


def _filled() -> str:
    return (
        TEMPLATE.replace(
            "## Zusammenfassung\n", "## Zusammenfassung\n\nNeuer Sensor.\n"
        )
        .replace(
            "## Belege\n",
            "## Belege\n\n- https://help.healthyapps.dev/en/health-auto-export/\n",
        )
        .replace("## Änderungen\n", "## Änderungen\n\n- `sensor.py`: neuer Sensor\n")
        .replace(
            "## Verhaltensänderungen\n",
            "## Verhaltensänderungen\n\n- Neuer Sensor, sonst nichts\n",
        )
        .replace("- Automatische Tests:", "- Automatische Tests: 40, davon 2 neu")
        .replace("- Gegenprobe:", "- Gegenprobe: 2 entfernt, beide erkannt")
        .replace("- Live geprüft:", "- Live geprüft: nein (noch kein Training)")
        .replace(
            "## Nicht geprüft / offen\n",
            "## Nicht geprüft / offen\n\n- Pulsraster Sekunden nicht live\n",
        )
        .replace("- [ ] ", "- [x] ")
    )


def test_filled_template_passes():
    assert pruefe_pr.pruefe_beschreibung(_filled()) == []


def test_empty_body_fails():
    errors = pruefe_pr.pruefe_beschreibung("")
    assert any("Zusammenfassung" in e for e in errors)


def test_open_box_and_live_format():
    body = _filled().replace("- [x] `ruff", "- [ ] `ruff", 1)
    body = body.replace("nein (noch kein Training)", "vielleicht")
    errors = pruefe_pr.pruefe_beschreibung(body)
    assert any("offen" in e for e in errors)
    assert any("Live geprüft" in e for e in errors)


def test_version_rule():
    changed = ["custom_components/ha_training/sensor.py"]
    assert pruefe_pr.pruefe_version(changed, "0.1.0", "0.1.0", set())
    assert pruefe_pr.pruefe_version(changed, "0.1.0", "0.1.1", set())
    assert pruefe_pr.pruefe_version(changed, "0.1.0", "0.1.1", {"v0.1.1.md"}) == []
    assert pruefe_pr.pruefe_version(["README.md"], "0.1.0", "0.1.0", set()) == []
