<!--
Pflichtvorlage. Die Prüfung „PR-Vorlage“ schlägt fehl, solange ein Abschnitt
fehlt oder leer ist, ein Feld nach dem Doppelpunkt leer bleibt oder ein
Kästchen offen ist. Trifft ein Punkt nicht zu: Kästchen ankreuzen und
„entfällt: <Grund>“ dahinter schreiben. Kommentare wie dieser dürfen bleiben.
-->

## Zusammenfassung

<!-- Was ändert sich für Nutzer? 1–3 Sätze. -->

## Belege

<!-- Quellen für Feldnamen und Einheiten: Doku von Health Auto Export (Link),
Home-Assistant-Doku, echter Export (nur Feldnamen, nie Koordinaten).
Ohne externe Quelle: „Keine: <Grund>“, auch als Listenpunkt. -->

## Änderungen

<!-- Ein Punkt je Datei oder Bereich. -->

## Verhaltensänderungen

<!-- Was ändert sich für bestehende Installationen? Neue oder entfallene
Entitäten, geänderte Entitäts-IDs, anderes Format im Speicher. Sonst:
„Keine: <Begründung>“. -->

## Tests

- Automatische Tests:
- Gegenprobe:
- Live geprüft:

<!-- Automatische Tests: Anzahl gesamt und neu, z. B. „40, davon 8 neu“.
Gegenprobe: welche Schutzmaßnahmen einzeln entfernt, mit Ergebnis.
Live geprüft: „ja (HA-Version, was)“ oder „nein (Grund)“. -->

## Nicht geprüft / offen

<!-- Was ist unbelegt oder ungetestet? „Nichts“ nur, wenn alles live geprüft ist. -->

## Checkliste

- [ ] `ruff check .` und `ruff format --check .` ohne Befund
- [ ] `pytest tests` vollständig grün, auch `test_repo_konsistenz.py` und `test_datenschutz.py`
- [ ] Feldnamen und Einheiten nach der Doku von Health Auto Export oder einem echten Export
- [ ] Texte in `strings.json`, `en.json` und `de.json`; Symbol in `icons.json`
- [ ] Keine Koordinaten, Routen oder Exporte im Diff, keine Webhook-ID im Log oder in der Diagnose
- [ ] README: Entitäten, Karte und Teststand mit aktueller Testzahl
- [ ] Version in `manifest.json` und in der Karte erhöht, `.github/release-notes/v<Version>.md` angelegt
