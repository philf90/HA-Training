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
Version 0.1.9.

## Inhalt

- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Einrichtung](#einrichtung)
- [Health Auto Export einstellen](#health-auto-export-einstellen)
- [Webhook mit Token absichern](#webhook-mit-token-absichern)
- [Adresse oder Token erneuern](#adresse-oder-token-erneuern)
- [Entitäten](#entitäten)
- [Karte „Training“](#karte-training)
- [Training löschen](#training-löschen)
- [GPX-Export](#gpx-export)
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
Integration legt zwei Geheimnisse an und zeigt beide nach dem Einrichten an,
später jederzeit unter Einstellungen → Geräte & Dienste → Training →
„Konfigurieren“:

- die **Webhook-Adresse**

  ```
  https://<deine-adresse>/api/webhook/<geheime-id>
  ```

- den **Wert für den HTTP-Header** `Authorization`: das Wort `Bearer`, ein
  Leerzeichen und der Token (43 Zeichen aus Buchstaben, Ziffern, `-` und `_`)

  ```
  Bearer <token>
  ```

Beides erzeugt die Integration selbst (je 256 Bit Zufall); man muss und kann
keinen eigenen Token ausdenken. Eine neu eingerichtete Integration nimmt
Aufrufe nur mit diesem Header an. Beides gehört nur in Health Auto Export. Ist
in Home Assistant keine Adresse eingestellt, zeigt der Dialog nur den Pfad
`/api/webhook/<geheime-id>`.

Unter „Konfigurieren“ steht außerdem, wie viele Trainings ihre Route und
Verläufe behalten (Standard 200, 10–2000; ältere Trainings behalten ihre
Zusammenfassung), der Schalter „Token verlangen“ und, falls es Konten ohne
Administratorrechte gibt, die Auswahl „Weitere Konten, die Routen sehen
dürfen“ (siehe [Datenschutz und Speicher](#datenschutz-und-speicher)).

## Health Auto Export einstellen

In der App auf dem iPhone **Export → Automated** öffnen (iPad: **Automations**
in der Seitenleiste), **New Automation** wählen und als **Automation Type**
**REST API** einstellen (nicht „Home Assistant“: dieser Typ sendet laut Doku
nur Gesundheitswerte, keine Trainings).

| Einstellung | Wert |
|---|---|
| URL | die Webhook-Adresse aus der Einrichtung |
| HTTP Headers | Schlüssel `Authorization`, Wert `Bearer <token>` aus der Einrichtung (siehe [unten](#webhook-mit-token-absichern)) |
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
`trainings`, `neu`, `geaendert`, `verworfen` und `geloescht` (schon einmal
gelöscht, deshalb nicht wieder angelegt, siehe
[Training löschen](#training-löschen)). Verworfen wird ein Training
ohne ID oder Beginn, mit einer ID aus anderen Zeichen als Buchstaben, Ziffern,
`_` und `-` (oder länger als 128 Zeichen) oder mit unerwartetem Aufbau; die
übrigen Trainings desselben Aufrufs werden trotzdem gespeichert.

Zum Schluss **Enabled** einschalten und mit **Update** speichern. Zum Testen
in der Automation unter **Export Existing Data** → **Manual Upload** einen
Zeitraum wählen und **Begin Export**; das Ergebnis steht unter **View Activity
Logs**.

## Webhook mit Token absichern

Die Webhook-Adresse steht im Pfad der URL und damit z. B. in den
Zugriffsprotokollen eines Reverse-Proxys. Der Token steht in einem HTTP-Header,
den solche Protokolle üblicherweise nicht aufzeichnen. Mit „Token verlangen“
lehnt der Webhook jeden Aufruf ohne den richtigen Header mit HTTP 401 ab, noch
bevor er den Inhalt liest.

**Neu eingerichtet (ab 0.1.5):** Der Token ist von Anfang an Pflicht. Den Header
wie in der Tabelle oben in Health Auto Export eintragen, sonst kommen keine
Trainings an.

**Aktualisiert von 0.1.4 oder älter:** Beim ersten Start legt die Integration
einen Token an, „Token verlangen“ bleibt aber aus, damit die App weiter
liefert. Zum Einschalten genau in dieser Reihenfolge:

1. **Token holen.** In Home Assistant: Einstellungen → Geräte & Dienste →
   Training → „Konfigurieren“. Der Dialog zeigt den Header-Wert
   `Bearer <token>`. Den Dialog mit „Absenden“ oder dem Kreuz schließen;
   dabei ändert sich nichts.
2. **In Health Auto Export eintragen.** Auf dem iPhone **Export → Automated**
   (iPad: **Automations**), die REST-API-Automation für Training öffnen und
   unter **HTTP Headers** einen Header anlegen:
   - Schlüssel: `Authorization`
   - Wert: `Bearer <token>`, also das Wort `Bearer`, ein Leerzeichen und die
     43 Zeichen des Tokens, ohne Anführungszeichen und ohne Leerzeichen am Ende

   Mit **Update** speichern.
3. **Testen.** In der Automation unter **Export Existing Data** →
   **Manual Upload** einen kurzen Zeitraum wählen und **Begin Export**. Unter
   **View Activity Logs** darf kein Fehler stehen. Die App schickt den Header
   schon mit, auch solange Home Assistant ihn noch nicht verlangt.
4. **Pflicht einschalten.** In Home Assistant wieder „Konfigurieren“, „Token
   verlangen“ einschalten, „Absenden“. Das wirkt sofort, ohne Neustart.
5. **Noch einmal testen** wie in Schritt 3.

Schlägt der Test nach Schritt 4 fehl, zeigt **View Activity Logs** in der App
einen Fehler beim Hochladen, und das Log von Home Assistant meldet „Webhook:
Aufruf ohne gueltigen Token abgelehnt“. Dann den Header-Wert in der App
prüfen (Schlüssel genau `Authorization`, Wert beginnt mit `Bearer `) oder
„Token verlangen“ wieder ausschalten.

Home Assistant wertet den Header `Authorization` auch selbst aus. Ein Token der
Integration ist dort unbekannt; der Aufruf gilt dann nur als „nicht
angemeldet“, was der Webhook nicht braucht. Fehlversuche zählen nicht als
Anmeldeversuche und führen nicht zur Sperre der IP-Adresse.

Laut Doku von Health Auto Export werden Request-Header in der iCloud-Sicherung
der Automationen verschlüsselt („Request headers and credentials you typed
into an automation … are encrypted in iCloud Drive backup files“). Für die URL
sagt die Doku das nicht.

## Adresse oder Token erneuern

Wenn Adresse oder Token bekannt geworden sein könnten: Einstellungen → Geräte &
Dienste → Training → Menü (⋮) → „Neu konfigurieren“. Dort „Neue
Webhook-Adresse“, „Neuer Token“ oder beides einschalten und „Absenden“. Der
Dialog zeigt danach die neuen Werte, „Konfigurieren“ ebenfalls. Die alten
gelten sofort nicht mehr; die gespeicherten Trainings bleiben erhalten. Die
neuen Werte danach in der Automation von Health Auto Export eintragen (URL
bzw. Header-Wert) und wie oben testen. Bis dahin kann die App nicht liefern;
was sie in der Zeit nicht schicken konnte, holt **Manual Upload** nach.

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
| `sensor.training_trainings_letzte_woche` | Anzahl Montag bis Sonntag der Vorwoche |
| `sensor.training_distanz_letzte_woche` | km der Vorwoche |
| `sensor.training_trainingszeit_letzte_woche` | Minuten der Vorwoche |
| `sensor.training_aktive_energie_letzte_woche` | kcal der Vorwoche |
| `event.training_neues_training` | Ereignis `neues_training` je neuem Training |

Die Summen „diese Woche“ haben `state_class: total` mit `last_reset` am Montag
00:00. Die Summen „letzte Woche“ rechnen jederzeit neu und haben keine
`state_class`: Kommt ein Training vom Sonntagabend erst am Montag an (iOS
entscheidet, wann Health Auto Export sendet), zählt es dort; in „diese Woche“
zählt es nicht, und die Langzeitstatistik der abgeschlossenen Woche bleibt ohne
dieses Training.

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
# optional, eigener Kachelserver statt OpenStreetMap:
# tile_url: https://tiles.example.org/{z}/{x}/{y}.png
# tile_attribution: © Beispiel-Karten
```

- `workout` mit einer ID lädt genau dieses Training, auch wenn es älter als
  die letzten 30 ist. Gibt es die ID nicht (mehr), zeigt die Karte das neueste
  Training und einen Hinweis.
- `tile_url` muss mit `https://` beginnen und `{z}`, `{x}` und `{y}` enthalten,
  sonst nimmt die Karte OpenStreetMap. `tile_attribution` erscheint als Text
  unten rechts in der Karte (Quellenangabe des Anbieters).
- Kopf mit Name, Datum, Uhrzeit und einer Auswahl der letzten 30 Trainings
  (dazu das fest eingestellte, wenn es älter ist).
- Die Karte lädt von selbst neu, wenn ein Training dazukommt, sich ändert
  (z. B. später mit Route nachgeschickt) oder gelöscht wird und wenn sich die
  Einstellungen unter „Konfigurieren“ ändern.
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
  Hat ein Training weniger als 30 Werte, gelten feste Grenzen. Das Tempo für
  die Farbe ist über eine Minute geglättet (Median ±30 s), das Diagramm über
  15 s: Die Route zeigt längere Abschnitte statt jeder kleinen Schwankung,
  dafür erscheinen Stopps unter etwa 30 s dort nicht mehr violett (im
  Diagramm weiterhin).
- Markiert sind Start, Ziel, Kilometer, Pausen und die Minute mit dem
  höchsten Puls. Nahe Marken werden zusammengefasst.
- Puls (Ø mit Band min–max) und Tempo als zwei Diagramme mit gemeinsamer
  Zeitachse; Tippen in ein Diagramm oder auf die Route zeigt dieselbe Stelle
  überall.
- Kilometer-Splits von Apple mit Zeit, min/km, km/h, Ø und max Puls.
- Oben rechts „GPX“ (lädt die Route als Datei, siehe [GPX-Export](#gpx-export))
  und für Administratoren „Löschen“ (siehe [Training löschen](#training-löschen)).
  Auf schmalen Karten stehen beide in einer eigenen Zeile unter dem Titel.

Farben, Rand und Schatten der Hülle aus dem Nachtblau-Stil (`--nachtblau-…`),
ohne dieses Theme mit festen Werten. Im dunklen Modus wird die Karte von OpenStreetMap umgefärbt. Leaflet
1.9.4 liegt der Integration bei (BSD-2-Lizenz, `frontend/leaflet/LICENSE`).
Nach einem Update einmal die Seite neu laden, in der Companion App den
Frontend-Cache zurücksetzen.

## Training löschen

Zum Beispiel ein Testtraining oder eine Fehlaufzeichnung. Löschen dürfen nur
Administratoren von Home Assistant.

**In der Karte:** das Training in der Auswahl im Kopf wählen, „Löschen“
tippen. Der Knopf zeigt dann „Wirklich löschen?“; ein zweites Tippen innerhalb
von 5 Sekunden löscht, sonst passiert nichts.

**Als Aktion,** z. B. in einem Skript. Die ID steht im Attribut `workout_id`
des Sensors „Letztes Training“ und des Ereignisses „Neues Training“:

```yaml
action: ha_training.delete_workout
data:
  workout_id: D6B529A9-0A4E-4E5A-818C-95C356458639
```

Was dabei passiert:

- Zusammenfassung, Route und Verläufe werden aus `.storage/` gelöscht.
- Die Sensoren rechnen sofort ohne das Training; „Letztes Training“ springt auf
  das vorherige. Die Wochensummen haben `state_class: total`, das laut Home
  Assistant steigen und fallen darf; die Langzeitstatistik verbucht das
  Löschen als Rückgang.
- Die ID kommt auf eine Sperrliste. Health Auto Export schickt je nach Zeitraum
  dieselben Trainings erneut; ein gelöschtes Training legt die Integration
  deshalb nicht wieder an und zählt es in der Antwort unter `geloescht`.
- Nicht gelöscht werden: Einträge im Verlauf und im Logbuch (z. B. das
  Ereignis „Neues Training“), schon geschickte Benachrichtigungen und Backups
  von Home Assistant, die das Training schon enthalten.

**Rückgängig:** `ha_training.undelete_workout` mit derselben `workout_id` nimmt
die ID von der Sperrliste. Das Training kommt mit der nächsten Übertragung aus
Health Auto Export zurück, die es enthält, z. B. per **Manual Upload** über den
passenden Zeitraum.

## GPX-Export

„GPX“ in der Karte lädt die Route des gewählten Trainings als GPX-1.1-Datei,
z. B. `training-2026-11-01-0945-outdoor-spaziergang.gpx`, für Strava, Komoot,
Garmin Connect oder ein anderes Programm. Jeder Punkt hat Position, Höhe und
Zeit (UTC); der Puls steht in der Garmin-Erweiterung `TrackPointExtension`
(je Punkt der letzte Messwert, höchstens 120 s alt). Eine Lücke von mehr als
10 Sekunden, z. B. eine Pause, beginnt ein neues Segment. Den Knopf gibt es nur,
solange das Training seine Route noch hat (siehe Aufbewahrung unter
„Konfigurieren“).

## Aktualisieren

HACS zeigt neue Versionen als Update an. Nach dem Herunterladen Home Assistant
neu starten, danach einmal die Seite neu laden, in der Companion App den
Frontend-Cache zurücksetzen.

**Update auf 0.1.9:** keine Migration. Vier neue Sensoren „… letzte Woche“
(siehe [Entitäten](#entitäten)); die Karte lädt bei Änderungen von selbst neu.

**Update auf 0.1.8:** keine Migration. Die Karte lädt eine fest eingestellte
Trainings-ID direkt und schickt OpenStreetMap jetzt den Ursprung der
Home-Assistant-Adresse als Referer (siehe [Datenschutz und Speicher](#datenschutz-und-speicher)).

**Update auf 0.1.7:** keine Migration. Die Annahme am Webhook blockiert
Home Assistant nicht mehr während großer Abgleiche (siehe Release-Hinweise);
neu ist die Obergrenze von 1000 Trainings je Aufruf. **Konten ohne
Administratorrechte sehen ab jetzt keine Routen mehr**, bis sie unter
„Konfigurieren“ freigegeben werden.

**Update auf 0.1.6:** keine Migration. Neu sind Löschen und GPX-Export; die
Antwort des Webhooks hat den zusätzlichen Schlüssel `geloescht`.

**Update auf 0.1.5:** Der Eintrag wird beim ersten Start auf Version 1.2
umgestellt: Er bekommt einen Token, „Token verlangen“ bleibt aus. Health Auto
Export liefert also weiter wie bisher; das Einschalten beschreibt
[Webhook mit Token absichern](#webhook-mit-token-absichern). Zurück auf 0.1.4
geht ohne Backup, dann prüft der Webhook den Token aber nicht mehr.

## Datenschutz und Speicher

- Eine GPS-Route zeigt Wohnort und Wege. Die Integration speichert Trainings
  unter `.storage/` (Dateien `ha_training.*`), nicht unter `www/`: Was unter
  `/local/` liegt, liefert Home Assistant ohne Anmeldung aus.
- Route und Verläufe verlassen Home Assistant nur über die WebSocket-API
  (`ha_training/workout`, `ha_training/gpx`) und nur für Administratoren und
  die Konten, die unter „Konfigurieren“ bei „Weitere Konten, die Routen sehen
  dürfen“ ausgewählt sind. Alle anderen angemeldeten Konten sehen in der Karte
  nur die Zusammenfassung (Distanz, Zeit, Puls, Energie) mit dem Hinweis, dass
  die Route nicht freigegeben ist. Dieselben Werte zeigen auch die Sensoren;
  Home Assistant kennt keine Rechte je Entität.
- Die Diagnose enthält weder die Webhook-ID noch den Token noch Koordinaten,
  von den Details nur Anzahlen. Ins Log schreibt die Integration keines der
  beiden Geheimnisse.
- Backups von Home Assistant enthalten `.storage/` und damit die Routen.
- Entfernen der Integration löscht alle gespeicherten Trainings; einzelne
  Trainings löscht [Training löschen](#training-löschen).
- Die Kartenkacheln lädt der Browser direkt bei OpenStreetMap (oder beim
  Anbieter aus `tile_url`). Der Anbieter sieht dabei die IP-Adresse und welche
  Kacheln abgerufen werden, also ungefähr das Gebiet der Route, und seit 0.1.8
  als Referer den Ursprung der Home-Assistant-Adresse (z. B.
  `https://mein-ha.example/`, ohne Pfad). Die Richtlinie der OSM-Kachelserver
  verlangt von Webseiten einen Referer; Home Assistant selbst schickt keinen
  (`Referrer-Policy: no-referrer`), deshalb setzt die Karte ihn nur für die
  Kacheln. Die Koordinaten der Route verlassen Home Assistant dabei nicht. Wer
  das vermeiden will, trägt mit `tile_url` einen eigenen Kachelserver ein.
- Eine GPX-Datei aus dem [GPX-Export](#gpx-export) enthält die Route und liegt
  danach außerhalb von Home Assistant, dort, wo der Browser sie speichert.
- Eine Stunde Gehen mit einem GPS-Punkt pro Sekunde braucht rund 170 KB.

## Grenzen

- Nur Exportversion 2 ist vollständig geprüft; Version 1 wird gelesen, soweit
  ihre Felder passen (Route mit `lat`/`lon`, Puls mit `qty`).
- Ein Aufruf darf höchstens 16 MB groß sein (Grenze von Home Assistant) und
  höchstens 1000 Trainings enthalten; sonst antwortet der Webhook mit HTTP 413
  und `{"fehler": "zu viele Trainings", "maximal": 1000}`. Eine Stunde Training
  mit Route und Puls im Sekundentakt braucht im JSON von Health Auto Export rund
  1 MB (gemessen: 3,08 MB für drei Stunden), an die 1000 kommt also nur ein
  Abgleich ohne Routen heran. Für einen großen ersten Abgleich den Zeitraum
  in Health Auto Export kürzer wählen oder dort **Batch Requests** einschalten
  (verteilt die Daten auf mehrere Aufrufe).
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
- Der GPX-Download ist nur in Chromium geprüft, nicht in Safari und nicht in
  der Companion App auf dem iPhone.

## Teststand

- **0.1.x:** 140 automatische Tests. 0.1.9: Nachzügler vom Sonntag in der
  letzten Woche, Grenzen der Woche (Montag 00:00 beidseitig), Vorwoche über die
  Zeitumstellung, Zähler `revision` bei Änderung, Löschen und Optionen, nicht
  im Verlauf, Karte lädt bei neuem Zähler und sucht die Entität nur einmal.
  0.1.8: fest eingestellte ältere ID direkt
  geladen und in der Auswahl, fehlende ID mit Rückfall und Hinweis, eigene
  Kachel-URL nur als https mit {z}/{x}/{y}, Quellenangabe als Text; Referer der
  Kacheln in Chromium geprüft. 0.1.7: Route, Verläufe und GPX nur für
  Administratoren und freigegebene Konten (Auswahl ohne Administratoren,
  veraltete Konten fallen heraus, Hinweis in der Karte); Dekodieren und Parsen außerhalb
  des Event-Loops, Obergrenze je Aufruf (413, genau an der Grenze 200), leerer
  Inhalt, Detaildateien nur innerhalb der Aufbewahrung, dieselbe ID zweimal in
  einem Aufruf, Speichern ohne Serialisieren im Event-Loop, Wochensummen mit
  frühem Abbruch auch bei Zeitstempeln mit verschiedenen UTC-Offsets.
  0.1.6: Löschen über Aktion und
  WebSocket (Sensoren rechnen neu, Detaildatei weg, nur für Administratoren),
  Sperrliste gegen erneutes Senden und über einen Neustart, wieder annehmen,
  unbekannte IDs, Löschen während Annahme und Ausdünnen (Lock), GPX mit
  Punkten, Segmenten, Puls und geschütztem Namen, Karte mit Rückfrage und
  Knopf nur für Administratoren. 0.1.5: IDs nur aus Zeichen, die der
  Dateiname unverändert übernimmt; Token im Header (fehlt, falsch,
  anderes Schema, Groß-/Kleinschreibung von `Bearer`, Ablehnung vor dem
  Parsen), Neueinrichtung mit Token-Pflicht, Migration von 0.1.4 ohne Pflicht,
  Schalter wirkt ohne Neuladen, „Neu konfigurieren“ für Adresse und Token
  (alte Adresse verarbeitet nichts mehr, Trainings bleiben, nichts gewählt),
  Token nicht in Diagnose und Log, falscher Token führt nicht zur IP-Sperre.
  0.1.4: ID mit unsicheren Zeichen oder
  zu lang wird verworfen, in der Karte escapt; unerwartete Feldtypen und
  übergroße Zahlen verwerfen weder das Training noch den Aufruf; ein
  unerwarteter Fehler verwirft nur sein Training; erneut geschickte Trainings
  hinter der Aufbewahrung schreiben keine Dateien, innerhalb holen sie fehlende
  Details zurück. 0.1.3: Glättung der Routenfarbe
  (kurzer Abschnitt bleibt im Diagramm, nicht in der Farbe; Fenster nach
  Zeit, nicht nach Index). 0.1.2: Stufen aus dem Training
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
  im Dashboard (0.1.1 und 0.1.2, iPhone; mit 0.1.2 Karte unter den Leisten,
  Marken und Farben bestätigt).

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
