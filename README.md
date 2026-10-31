<p align="center">
  <img src="https://raw.githubusercontent.com/philf90/HA-Training/main/assets/icon.svg" alt="Training" width="96">
</p>

# Training

[![Erstellt mit Claude Code](https://img.shields.io/badge/erstellt%20mit-Claude%20Code-D97757?logo=claude&logoColor=white)](https://claude.com/claude-code)
[![KI-generiert](https://img.shields.io/badge/Code%20%26%20Doku-KI--generiert-6A2BB0)](#ki-hinweis)

Home-Assistant-Integration für Trainings der Apple Watch: Die iOS-App
[Health Auto Export](https://healthyapps.dev) schickt jedes Training samt
GPS-Route, Puls- und Tempoverlauf, Pausen und Kilometer-Splits an einen Webhook
dieser Integration. Home Assistant speichert die Trainings privat, zeigt das
letzte Training und die Woche als Sensoren und meldet neue Trainings als
Ereignis. Die mitgelieferte Karte zeichnet die Route auf einer Karte, nach
Tempo oder Puls eingefärbt, mit gekoppeltem Verlauf und Kilometer-Tabelle.
Version 0.1.2.

## Inhalt

- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Einrichtung](#einrichtung)
- [Health Auto Export einstellen](#health-auto-export-einstellen)
- [Entitäten](#entitäten)
- [Karte „Training“](#karte-training)
- [Aktualisieren](#aktualisieren)
- [Datenschutz und Speicher](#datenschutz-und-speicher)
- [Grenzen](#grenzen)
- [Teststand](#teststand)
- [Tests](#tests)
- [KI-Hinweis](#ki-hinweis)
- [Lizenz](#lizenz)

## Voraussetzungen

- Home Assistant 2026.2.3 oder neuer.
- iPhone mit [Health Auto Export – JSON+CSV](https://apps.apple.com/app/id1115567069)
  und Premium: Nur damit sendet die App automatisch („Automations“).
- Für die Übertragung von unterwegs eine von außen erreichbare Adresse von
  Home Assistant (Einstellungen → System → Netzwerk → Home Assistant-URL).

## Installation

Über HACS als benutzerdefiniertes Repository:

1. HACS → Drei-Punkte-Menü → Benutzerdefinierte Repositories →
   `https://github.com/philf90/HA-Training`, Typ „Integration“.
2. „Training“ herunterladen, Home Assistant neu starten.

Von Hand: Ordner `custom_components/ha_training` samt `translations/`,
`frontend/` und `brand/` nach `config/custom_components/` kopieren und neu
starten.

## Einrichtung

Einstellungen → Geräte & Dienste → Integration hinzufügen → „Training“. Die
Integration legt eine geheime Webhook-Adresse an und zeigt sie nach dem
Einrichten an, später jederzeit unter „Konfigurieren“:

```
https://<deine-adresse>/api/webhook/<geheime-id>
```

Wer die Adresse kennt, kann Trainings anlegen. Sie gehört deshalb nur in
Health Auto Export. Ist in Home Assistant keine Adresse eingestellt, zeigt der
Dialog nur den Pfad `/api/webhook/<geheime-id>`.

Unter „Konfigurieren“ steht außerdem, wie viele Trainings ihre Route und
Verläufe behalten (Standard 200, 10–2000). Ältere Trainings behalten ihre
Zusammenfassung.

## Health Auto Export einstellen

In der App: Automations → neue Automation → Typ **REST API** (nicht „Home
Assistant“: dieser Typ sendet laut Doku nur Gesundheitswerte, keine Trainings).

| Einstellung | Wert |
|---|---|
| URL | die Webhook-Adresse aus der Einrichtung |
| Methode | POST |
| Datentyp | Workouts |
| Exportformat | JSON |
| Exportversion | 2 |
| Include Route Data | an |
| Include Workout Metrics | an |
| Time Grouping | Seconds (feinerer Puls; „Minutes“ geht auch) |

Die App schickt je nach Zeitraum dieselben Trainings mehrmals. Die Integration
erkennt sie an der ID aus Apple Health; ein erneut geschicktes Training ersetzt
das alte nur, wenn sich etwas geändert hat. Die Antwort des Webhooks nennt
`trainings`, `neu`, `geaendert` und `verworfen`.

## Entitäten

Ein Gerät „Training“ mit diesen Entitäten. Die IDs entstehen aus der Sprache
der Instanz; in einer deutschen Instanz z. B.:

| Entität | Inhalt |
|---|---|
| `sensor.training_letztes_training` | Beginn des letzten Trainings (Zeitstempel); Attribute `workout_id`, `name`, `location`, `end` |
| `sensor.training_letztes_training_distanz` | km |
| `sensor.training_letztes_training_dauer` | aktive Minuten (ohne Pausen) |
| `sensor.training_letztes_training_tempo` | Ø km/h |
| `sensor.training_letztes_training_puls_durchschnitt` | bpm |
| `sensor.training_letztes_training_puls_maximum` | bpm |
| `sensor.training_letztes_training_aktive_energie` | kcal |
| `sensor.training_letztes_training_anstrengung` | Apples geschätzte Anstrengung (1–10) |
| `sensor.training_letztes_training_hohenmeter` | m bergauf |
| `sensor.training_trainings_diese_woche` | Anzahl seit Montag 00:00 |
| `sensor.training_distanz_diese_woche` | km seit Montag |
| `sensor.training_trainingszeit_diese_woche` | Minuten seit Montag |
| `sensor.training_aktive_energie_diese_woche` | kcal seit Montag |
| `event.training_neues_training` | Ereignis `neues_training` je neuem Training |

Die Wochensummen haben `state_class: total` mit `last_reset` am Montag 00:00.

Das Ereignis trägt `workout_id`, `name`, `start`, `end`, `distance_km`,
`duration_s`, `speed_kmh`, `hr_avg`, `hr_max`, `active_kcal`, `effort` und
`elevation_up_m`, nie die Route. Es löst nur für Trainings aus, die höchstens
24 Stunden vorbei sind; beim ersten Abgleich mit vielen alten Trainings kommt
so keine Flut. Beispiel für eine Push-Nachricht:

```yaml
triggers:
  - trigger: state
    entity_id: event.training_neues_training
    not_from: [unavailable, unknown]
actions:
  - action: notify.mobile_app_iphone
    data:
      title: "{{ trigger.to_state.attributes.name }}"
      message: >-
        {{ trigger.to_state.attributes.distance_km | round(2) }} km ·
        {{ (trigger.to_state.attributes.duration_s / 60) | round(0) | int }} min ·
        Ø Puls {{ trigger.to_state.attributes.hr_avg | round(0) | int }}
```

## Karte „Training“

Die Integration liefert die Karte selbst aus und lädt sie im Frontend; eine
Dashboard-Ressource oder weitere HACS-Karten sind nicht nötig.

```yaml
type: custom:ha-training-card
workout: latest      # oder die id eines Trainings (Attribut workout_id)
color_by: speed      # oder heart_rate
```

- Kopf mit Name, Datum, Uhrzeit und einer Auswahl der letzten 30 Trainings.
- Kennzahlen: Distanz (dazu die Länge der GPS-Route), Zeit aktiv mit Pause,
  Tempo und min/km, Puls, aktive Energie, Anstrengung, Höhenmeter,
  Schrittfrequenz, Temperatur und Luftfeuchte.
- Route auf OpenStreetMap, nach Tempo oder Puls in fünf Stufen eingefärbt.
  Die Grenzen kommen aus dem jeweiligen Training: Tempo unter 1 km/h ist
  „Stopp“, der Rest in Vierteln der Zeit in Bewegung; Puls in Fünfteln der
  Zeit. So zeigt die Farbe, wo man in diesem Training schneller oder
  langsamer war; die Legende nennt die Werte. Farbreihen aus der Palette:
  Tempo Violett, Blau, Mint, Limette, Sonnengelb; Puls Blau, Mint, Limette,
  Amber, Koralle (benachbarte Stufen mindestens ΔE 2000 = 16 auseinander).
  Hat ein Training weniger als 30 Werte, gelten feste Grenzen.
- Markiert sind Start, Ziel, Kilometer, Pausen und die Minute mit dem
  höchsten Puls. Nahe Marken werden zusammengefasst.
- Puls (Ø mit Band min–max) und Tempo als zwei Diagramme mit gemeinsamer
  Zeitachse; Tippen in ein Diagramm oder auf die Route zeigt dieselbe Stelle
  überall.
- Kilometer-Splits von Apple mit Zeit, min/km, km/h, Ø und max Puls.

Farben, Rand und Schatten der Hülle aus dem Nachtblau-Stil (`--nachtblau-…`),
ohne dieses Theme mit festen Werten. Im dunklen Modus wird die Karte von OpenStreetMap umgefärbt. Leaflet
1.9.4 liegt der Integration bei (BSD-2-Lizenz, `frontend/leaflet/LICENSE`).
Nach einem Update einmal die Seite neu laden, in der Companion App den
Frontend-Cache zurücksetzen.

## Aktualisieren

HACS zeigt neue Versionen als Update an. Nach dem Herunterladen Home Assistant
neu starten, danach einmal die Seite neu laden, in der Companion App den
Frontend-Cache zurücksetzen.

**Update auf 0.1.2:** keine Migration. Nur die Karte ändert sich (siehe
Release-Hinweise).

## Datenschutz und Speicher

- Eine GPS-Route zeigt Wohnort und Wege. Die Integration speichert Trainings
  unter `.storage/` (Dateien `ha_training.*`), nicht unter `www/`: Was unter
  `/local/` liegt, liefert Home Assistant ohne Anmeldung aus.
- Route und Verläufe verlassen Home Assistant nur über die WebSocket-API
  (`ha_training/workouts`, `ha_training/workout`), also nur für angemeldete
  Nutzer.
- Die Diagnose enthält weder die Webhook-ID noch Koordinaten, von den Details
  nur Anzahlen.
- Backups von Home Assistant enthalten `.storage/` und damit die Routen.
- Entfernen der Integration löscht alle gespeicherten Trainings.
- Eine Stunde Gehen mit einem GPS-Punkt pro Sekunde braucht rund 170 KB.

## Grenzen

- Nur Exportversion 2 ist vollständig geprüft; Version 1 wird gelesen, soweit
  ihre Felder passen (Route mit `lat`/`lon`, Puls mit `qty`).
- Ein Aufruf darf höchstens 16 MB groß sein (Grenze von Home Assistant). Für
  einen großen ersten Abgleich den Zeitraum in Health Auto Export kürzer
  wählen.
- Der Puls kommt so fein wie in der App eingestellt (Minuten oder Sekunden).
  Hat die Uhr zeitweise nicht gemessen, bleibt die Linie dort offen und die
  Route grau; einzelne Werte in einer Lücke zeigt das Diagramm als Punkt.
- Die Distanz von Apple (Schrittzähler und GPS) und die Summe der GPS-Punkte
  weichen leicht voneinander ab (im Test 2,91 gegen 3,02 km). Die km-Marken auf
  der Karte und die km-Angabe beim Tippen folgen der Distanz von Apple (die
  GPS-Strecke wird darauf umgerechnet), damit sie zur Tabelle passen. Die
  Kachel „Distanz“ nennt beide Werte.
- Sendet Health Auto Export im Hintergrund, entscheidet iOS über den
  Zeitpunkt.

## Teststand

- **0.1.x:** 59 automatische Tests. 0.1.2: Stufen aus dem Training
  (Viertel, Fünftel, streng steigend, Rückfall bei wenigen Werten),
  Abschnitte und Einzelwerte in Lücken, Umrechnung GPS auf Apple-Distanz,
  Abstand der Farbstufen (ΔE 2000), Kartenfläche mit eigener Ebene unter den
  Leisten, Marken ohne Umbruch innerhalb einer Angabe. 0.1.1: Hülle der Karte mit Rand und
  Schatten wie die Nachtblau-Hüllen (keine neuen Tests). 0.1.0: Parser (Einheiten, Pausen, Splits,
  Version 1, fehlende Felder), Webhook (neu, doppelt, geändert, kein JSON, ohne
  ID, falsche Methode, nach dem Entladen), Einrichtung und Optionen samt
  Aufbewahrung, WebSocket-API, Ereignis nur für neue Trainings, Wochensummen
  mit Wechsel am Montag, Diagnose ohne Geheimnis und Route, Entfernen,
  Neustart, Datenschutz (keine Koordinaten, Exporte oder Webhook-ID im Repo
  bzw. Log), Konsistenz von Version, Übersetzungen und Karte, PR-Vorlage
  (auch erster PR ohne manifest.json auf main).
  Die Karte ist in Chromium bei 344 und 386 Pixeln mit synthetischen Daten und
  mit einem echten Export gezeichnet, ohne Fehler und ohne waagrechten
  Überlauf; Kennzahlen und Splits stimmen mit der App überein. Live geprüft
  (31.10.2026): Annahme über den Webhook aus Health Auto Export und die Karte
  im Dashboard (0.1.1, iPhone).

## Tests

```bash
pip install pytest-homeassistant-custom-component==0.13.316 ruff==0.16.9
ruff check . && ruff format --check .
python -m pytest tests -q
```

Die Tests nutzen eine erfundene Runde um den Großen Stern in Berlin. Echte
Exporte gehören nicht ins Repo; `test_datenschutz.py` schlägt bei Koordinaten
außerhalb dieser Runde, bei `.gpx`/`.zip` und bei Dateien von Health Auto
Export fehl.

## KI-Hinweis

Dieses Projekt wurde mit [Claude Code](https://claude.com/claude-code)
entwickelt, einem KI-Assistenten von Anthropic. Recherche, Code, Tests und
Dokumentation hat die KI im Auftrag und unter Anleitung des Repo-Inhabers
erstellt. Geprüft wurde mit automatischen Tests (`pytest`), `ruff`, Gegenproben
mit absichtlich entfernten Schutzmaßnahmen und Darstellungstests der Karte.
Feldnamen und Einheiten stammen aus der Doku von Health Auto Export
(„Workouts – JSON Export Format“) und einem echten Export vom 31.10.2026.

## Lizenz

MIT, siehe [LICENSE](LICENSE). Leaflet: BSD-2-Clause, siehe
`custom_components/ha_training/frontend/leaflet/LICENSE`.
