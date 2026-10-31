"""Konsistenz von Version, Doku, Uebersetzungen und Karte."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
BASE = ROOT / "custom_components" / "ha_training"
README = (ROOT / "README.md").read_text(encoding="utf-8")
MANIFEST = json.loads((BASE / "manifest.json").read_text())
VERSION = MANIFEST["version"]
MINOR = ".".join(VERSION.split(".")[:2])
CARD = (BASE / "frontend" / "ha-training-card.js").read_text(encoding="utf-8")


def test_version_in_readme_and_release_notes():
    assert f"Version {VERSION}." in README, "README nennt die Version nicht"
    notes = ROOT / ".github" / "release-notes" / f"v{VERSION}.md"
    assert notes.is_file(), f"{notes.name} fehlt"
    text = notes.read_text(encoding="utf-8")
    assert "## Neu" in text or "## Behoben" in text or "## Geändert" in text
    assert "## Teststand" in text


def test_readme_test_count_matches(request: pytest.FixtureRequest):
    items = request.session.items
    if len({Path(str(i.fspath)).name for i in items}) < len(
        list((ROOT / "tests").glob("test_*.py"))
    ):
        pytest.skip("nur beim Lauf aller Testdateien")
    match = re.search(
        rf"\*\*{re.escape(MINOR)}\.x:\*\* (\d+) automatische Tests", README
    )
    assert match, f"Teststand fuer {MINOR}.x fehlt im README"
    assert int(match.group(1)) == len(items)


def _flatten(data, prefix=""):
    if isinstance(data, dict):
        for key, value in data.items():
            yield from _flatten(value, f"{prefix}{key}.")
    else:
        yield prefix.rstrip("."), data


def test_translations_match():
    strings = json.loads((BASE / "strings.json").read_text(encoding="utf-8"))
    en = json.loads((BASE / "translations/en.json").read_text(encoding="utf-8"))
    de = dict(_flatten(json.loads((BASE / "translations/de.json").read_text())))
    assert strings == en, "strings.json und en.json weichen ab"
    flat_en = dict(_flatten(en))
    assert set(flat_en) == set(de), "de.json hat andere Schluessel"
    for key, text in flat_en.items():
        assert set(re.findall(r"\{\w+\}", text)) == set(
            re.findall(r"\{\w+\}", de[key])
        ), f"Platzhalter in {key}"


def test_every_entity_has_icon_and_name():
    from custom_components.ha_training.sensor import SENSORS

    icons = json.loads((BASE / "icons.json").read_text())["entity"]
    en = json.loads((BASE / "strings.json").read_text())["entity"]
    for description in SENSORS:
        assert description.translation_key in icons["sensor"]
        assert description.translation_key in en["sensor"]
    assert "new_workout" in icons["event"] and "new_workout" in en["event"]


def test_card_version_matches_manifest():
    assert f'const VERSION = "{VERSION}";' in CARD


def test_card_is_valid_javascript():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node fehlt")
    result = subprocess.run(
        [node, "--check", str(BASE / "frontend" / "ha-training-card.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_leaflet_is_shipped_with_license():
    leaflet = BASE / "frontend" / "leaflet"
    assert (leaflet / "leaflet.js").is_file()
    assert (leaflet / "leaflet.css").is_file()
    assert "BSD 2-Clause" in (leaflet / "LICENSE").read_text()


def test_hacs_and_manifest():
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["name"] == MANIFEST["name"]
    assert MANIFEST["domain"] == "ha_training"
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)
