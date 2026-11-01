/*
 * Karte "Training" (custom:ha-training-card) der Integration Training.
 *
 * Holt Trainings ueber die WebSocket-API der Integration (nur angemeldete
 * Nutzer): ha_training/workouts (Liste) und ha_training/workout (Details mit
 * Route und Verlaeufen). Zeigt Kennzahlen, die Route auf einer Karte (nach
 * Tempo oder Puls eingefaerbt), Puls- und Tempoverlauf mit gemeinsamer Zeitachse
 * und die Kilometer-Splits von Apple. Tippen in ein Diagramm oder auf die Route
 * markiert dieselbe Stelle ueberall.
 *
 * Optionen:
 *   type: custom:ha-training-card
 *   workout: latest        # oder die id eines Trainings
 *   color_by: speed        # oder heart_rate
 *   entry_id: ...          # nur bei mehreren Eintraegen noetig
 *
 * Leaflet 1.9.4 liefert die Integration unter /ha_training/leaflet/ mit
 * (BSD-2-Lizenz, siehe leaflet/LICENSE). Kartenkacheln: OpenStreetMap, im
 * dunklen Modus umgefaerbt. Farben aus dem Nachtblau-Stil, mit festen Werten
 * als Rueckfall.
 *
 * Einfaerbung der Route: Stufengrenzen aus dem jeweiligen Training (Tempo:
 * Stopp unter 1 km/h, dann Viertel der Zeit in Bewegung; Puls: Fuenftel der
 * Zeit), damit Unterschiede innerhalb eines Trainings sichtbar werden. Das
 * Tempo fuer die Farbe ist ueber eine Minute geglaettet (Median +-30 s), das
 * Diagramm ueber 15 s, damit die Route nicht bei jeder kleinen Schwankung
 * die Farbe wechselt.
 * Kilometer-Marken nach der Distanz von Apple (GPS-Strecke darauf skaliert),
 * damit sie zu den Splits passen.
 */

const VERSION = "0.1.5";
const LEAFLET = "/ha_training/leaflet";

const TEXT = {
  de: {
    title: "Training",
    none: "Noch keine Trainings. Health Auto Export schickt sie per REST-Automation an die Webhook-Adresse der Integration.",
    noEntry: "Die Integration Training ist nicht eingerichtet oder nicht geladen.",
    loading: "Lädt …",
    pruned: "Route und Verläufe dieses Trainings sind gelöscht (Aufbewahrung in den Optionen).",
    distance: "Distanz", active: "Zeit aktiv", total: "gesamt", pause: "Pause",
    speed: "Tempo Ø", hrAvg: "Puls Ø", energy: "Aktive Energie", effort: "Anstrengung",
    elevation: "Höhenmeter", cadence: "Schrittfrequenz", route: "Route", colorBy: "Farbe nach",
    byspeed: "Tempo", byhr: "Puls", course: "Verlauf", hrChart: "Puls (Ø, Band = min–max) · bpm",
    speedChart: "Tempo (über 15 s geglättet) · km/h", splits: "Kilometer",
    section: "Abschnitt", time: "Zeit aktiv", pace: "Tempo", hrAvgShort: "Ø Puls", hrMaxShort: "max Puls",
    hint: "Über ein Diagramm oder die Route fahren", start: "Start", finish: "Ziel",
    hrPeak: "Puls-Max", stop: "unter 1 (Stopp)", from: "ab", below: "unter",
    perKm: "min/km", appleEffort: "Apple-Schätzung", gpsRoute: "GPS-Route", min: "min", max: "max",
    noData: "keine Daten", height: "Höhe", humidity: "Luftfeuchte",
    levelsSpeed: "Stufen aus diesem Training: je ¼ der Zeit in Bewegung; Tempo für die Farbe über 1 min geglättet",
    levelsHr: "Stufen aus diesem Training: je ⅕ der Zeit",
  },
  en: {
    title: "Workout",
    none: "No workouts yet. Health Auto Export sends them to the webhook address of the integration via a REST automation.",
    noEntry: "The Training integration is not set up or not loaded.",
    loading: "Loading …",
    pruned: "Route and charts of this workout were deleted (retention in the options).",
    distance: "Distance", active: "Active time", total: "total", pause: "Pause",
    speed: "Avg speed", hrAvg: "Avg heart rate", energy: "Active energy", effort: "Effort",
    elevation: "Elevation gain", cadence: "Cadence", route: "Route", colorBy: "Color by",
    byspeed: "Speed", byhr: "Heart rate", course: "Course", hrChart: "Heart rate (avg, band = min–max) · bpm",
    speedChart: "Speed (15 s smoothed) · km/h", splits: "Kilometres",
    section: "Section", time: "Active time", pace: "Pace", hrAvgShort: "Avg HR", hrMaxShort: "Max HR",
    hint: "Move over a chart or the route", start: "Start", finish: "Finish",
    hrPeak: "Max HR", stop: "below 1 (stop)", from: "from", below: "below",
    perKm: "min/km", appleEffort: "Apple estimate", gpsRoute: "GPS route", min: "min", max: "max",
    noData: "no data", height: "Altitude", humidity: "humidity",
    levelsSpeed: "Levels from this workout: ¼ of the moving time each; speed for the colour smoothed over 1 min",
    levelsHr: "Levels from this workout: ⅕ of the time each",
  },
};

// Farbrollen (Nachtblau-Stil): Variable und fester Rueckfall
const COLORS = {
  surface: ["--nachtblau-flaeche-vertieft", "#10151d"],
  speed: ["--nachtblau-blau", "#7fb3d5"],
  hr: ["--nachtblau-rose", "#e6a0c4"],
  text: ["--nachtblau-text", "#f2f5f8"],
  muted: ["--nachtblau-text-sekundaer", "#8794a5"],
  off: ["--nachtblau-aus", "#3a4453"],
  violett: ["--nachtblau-violett", "#b399d4"],
  blau: ["--nachtblau-blau", "#7fb3d5"],
  mint: ["--nachtblau-mint", "#89d2b0"],
  limette: ["--nachtblau-limette", "#bdd27f"],
  sonnengelb: ["--nachtblau-sonnengelb", "#e6c15a"],
  amber: ["--nachtblau-amber", "#e6b566"],
  koralle: ["--nachtblau-koralle", "#e7936e"],
};

// Stufen der Route. Farbreihen aus der Palette mit deutlich verschiedenen
// Toenen (benachbarte Stufen mindestens Delta E 2000 = 16); "limits" gelten
// nur, wenn ein Training zu wenige Werte fuer eigene Grenzen hat.
const SCALES = {
  speed: {
    field: "vc", unit: "km/h", digits: 1, stop: 1, shares: [0.25, 0.5, 0.75],
    limits: [1, 2.5, 3.3, 3.8], ramp: ["violett", "blau", "mint", "limette", "sonnengelb"],
  },
  heart_rate: {
    field: "hr", unit: "bpm", digits: 0, shares: [0.2, 0.4, 0.6, 0.8],
    limits: [100, 105, 110, 115], ramp: ["blau", "mint", "limette", "amber", "koralle"],
  },
};
const MIN_VALUES = 30;
const GAP_S = 90;
const SMOOTH_CHART_S = 7;   // Diagramm: Median ueber +-7 s (15 s)
const SMOOTH_COLOR_S = 30;  // Farbe der Route: Median ueber +-30 s (1 min)

// Gleitender Median nach Zeit: fuer jeden Punkt der Median aller Werte
// innerhalb von +-half Sekunden (bei gerader Anzahl der obere). Fehlende
// Werte zaehlen nicht; ohne Wert im Fenster null.
function medianSmooth(times, values, half) {
  const out = new Array(times.length).fill(null);
  let lo = 0, hi = 0;
  for (let i = 0; i < times.length; i++) {
    while (times[lo] < times[i] - half) lo++;
    while (hi < times.length && times[hi] <= times[i] + half) hi++;
    const window = [];
    for (let j = lo; j < hi; j++) if (values[j] != null) window.push(values[j]);
    if (window.length) {
      window.sort((a, b) => a - b);
      out[i] = window[Math.floor(window.length / 2)];
    }
  }
  return out;
}

// Wert beim Anteil p einer sortierten Liste (linear zwischen Nachbarn)
function quantile(sorted, p) {
  const i = (sorted.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
}

// Stufengrenzen aus den Werten eines Trainings, gerundet wie in der Legende
// und streng steigend. Zu wenige Werte: feste Grenzen.
function workoutLimits(values, kind) {
  const scale = SCALES[kind];
  const step = 10 ** -scale.digits;
  const fix = (x) => Number(x.toFixed(scale.digits));
  const usable = values.filter((v) => v != null && !Number.isNaN(v) && (scale.stop == null || v >= scale.stop));
  if (usable.length < MIN_VALUES) return { limits: scale.limits.slice(), relative: false };
  usable.sort((a, b) => a - b);
  const raw = (scale.stop != null ? [scale.stop] : []).concat(scale.shares.map((p) => quantile(usable, p)));
  const limits = [];
  raw.forEach((x, i) => limits.push(fix(i ? Math.max(Math.round(x / step) * step, limits[i - 1] + step) : Math.round(x / step) * step)));
  return { limits, relative: true };
}

// Zusammenhaengende Abschnitte einer Reihe [t, v]; Luecken > gap oder
// fehlende Werte trennen. Einzelne Werte bilden Abschnitte der Laenge 1.
function splitRuns(rows, gap) {
  const runs = [];
  let run = [], last = null;
  for (const [t, v] of rows) {
    if (v == null || (last != null && t - last > gap)) { if (run.length) runs.push(run); run = []; }
    if (v != null) run.push([t, v]);
    last = t;
  }
  if (run.length) runs.push(run);
  return runs;
}

// Faktor von der GPS-Strecke auf die Distanz von Apple (1 ohne brauchbare Werte)
function distanceFactor(officialKm, gpsMetres) {
  if (!(officialKm > 0) || !(gpsMetres > 0)) return 1;
  const factor = (officialKm * 1000) / gpsMetres;
  return factor > 0.5 && factor < 2 ? factor : 1;
}

let leafletPromise = null;
function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (!leafletPromise) {
    leafletPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = `${LEAFLET}/leaflet.js?v=${VERSION}`;
      script.onload = () => resolve(window.L);
      script.onerror = () => { leafletPromise = null; reject(new Error("Leaflet")); };
      document.head.appendChild(script);
    });
  }
  return leafletPromise;
}

function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(String(hex).trim());
  return m ? m.slice(1).map((x) => parseInt(x, 16)) : null;
}
function mix(a, b, share) {
  const x = hexToRgb(a), y = hexToRgb(b);
  if (!x || !y) return a;
  const c = x.map((v, i) => Math.round(v * share + y[i] * (1 - share)));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

class HaTrainingCard extends HTMLElement {
  static getStubConfig() {
    return { workout: "latest", color_by: "speed" };
  }

  setConfig(config) {
    this._config = { workout: "latest", color_by: "speed", ...(config || {}) };
    this._colorBy = this._config.color_by === "heart_rate" ? "heart_rate" : "speed";
    this._selected = this._config.workout && this._config.workout !== "latest" ? this._config.workout : null;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._renderShell();
  }

  getCardSize() {
    return 14;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const latest = this._latestId(hass);
    if (first || latest !== this._latestSeen) {
      this._latestSeen = latest;
      this._loadList();
    }
  }

  connectedCallback() {
    // Zurueck im Dokument (z. B. nach Wechsel der Ansicht): neu zeichnen,
    // damit Karte und Diagramme wieder auf Groessenaenderungen reagieren
    if (this._summary && !this._resize) this._render();
  }

  disconnectedCallback() {
    if (this._resize) { this._resize.disconnect(); this._resize = null; }
  }

  _t(key) {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").slice(0, 2);
    return (TEXT[lang] || TEXT.en)[key] ?? TEXT.en[key] ?? key;
  }

  _locale() {
    return this._hass?.locale?.language || this._hass?.language || "de";
  }

  _num(x, digits = 0) {
    return x == null || Number.isNaN(x)
      ? "–"
      : Number(x).toLocaleString(this._locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  _clock(t, seconds = false) {
    const opts = { hour: "2-digit", minute: "2-digit", timeZone: this._hass?.config?.time_zone };
    if (seconds) opts.second = "2-digit";
    return new Date(t * 1000).toLocaleTimeString(this._locale(), opts);
  }

  _duration(s) {
    s = Math.round(s || 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return (h ? `${h}:${String(m).padStart(2, "0")}` : `${m}`) + ":" + String(x).padStart(2, "0");
  }

  _color(role) {
    const [name, fallback] = COLORS[role];
    const value = getComputedStyle(this).getPropertyValue(name).trim();
    return hexToRgb(value) ? value : fallback;
  }

  // Entitaet "Letztes Training" der Integration: Aenderung -> Liste neu laden
  _latestId(hass) {
    const entities = hass.entities || {};
    for (const id of Object.keys(entities)) {
      if (entities[id].platform === "ha_training" && id.startsWith("sensor.")) {
        const value = hass.states[id]?.attributes?.workout_id;
        if (value) return value;
      }
    }
    return null;
  }

  async _loadList() {
    if (!this._hass) return;
    const request = { type: "ha_training/workouts", limit: 30 };
    if (this._config.entry_id) request.entry_id = this._config.entry_id;
    try {
      const result = await this._hass.callWS(request);
      this._workouts = result.workouts || [];
      this._error = null;
    } catch (err) {
      this._workouts = [];
      this._error = "noEntry";
    }
    const id = this._selected && this._workouts.some((w) => w.id === this._selected)
      ? this._selected
      : this._workouts[0]?.id;
    if (id) await this._loadWorkout(id);
    else this._render();
  }

  async _loadWorkout(id) {
    const request = { type: "ha_training/workout", workout_id: id };
    if (this._config.entry_id) request.entry_id = this._config.entry_id;
    try {
      const result = await this._hass.callWS(request);
      this._summary = result.summary;
      this._prepare(result.detail);
    } catch (err) {
      this._summary = this._workouts.find((w) => w.id === id) || null;
      this._prepare(null);
    }
    this._current = id;
    this._render();
  }

  // Details in Punkte umwandeln: Tempo geglaettet, Puls je Punkt aus dem Verlauf
  _prepare(detail) {
    this._detail = detail;
    this._points = [];
    this._dFactor = 1;
    if (!detail) return;
    const hr = detail.heart_rate || [];
    const route = detail.route || [];
    let h = 0, dist = 0;
    for (let i = 0; i < route.length; i++) {
      const [t, lat, lon, alt, speed] = route[i];
      if (i) dist += this._metres(route[i - 1], route[i]);
      while (h + 1 < hr.length && hr[h + 1][0] <= t) h++;
      const sample = hr.length && hr[h][0] <= t && t - hr[h][0] < 120 ? hr[h][2] : null;
      this._points.push({ t, lat, lon, alt, speed, hr: sample, d: dist });
    }
    const times = this._points.map((p) => p.t);
    const speeds = this._points.map((p) => (p.speed == null ? null : p.speed * 3.6));
    const chart = medianSmooth(times, speeds, SMOOTH_CHART_S);
    const color = medianSmooth(times, speeds, SMOOTH_COLOR_S);
    this._points.forEach((p, i) => { p.v = chart[i]; p.vc = color[i]; });
    this._dFactor = distanceFactor(this._summary?.distance_km, dist);
  }

  _metres(a, b) {
    const R = 6371008.8, rad = Math.PI / 180;
    const dp = (b[1] - a[1]) * rad, dl = (b[2] - a[2]) * rad;
    const x = Math.sin(dp / 2) ** 2 + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(x));
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <link rel="stylesheet" href="${LEAFLET}/leaflet.css?v=${VERSION}">
      <style>
        :host { display: block; }
        ha-card { padding: 16px 18px; background: linear-gradient(180deg, var(--nachtblau-huelle-oben, var(--ha-card-background, #1b2231)) 0%, var(--nachtblau-huelle-unten, var(--ha-card-background, #171d29)) 55%); border-radius: 22px; border: 1px solid var(--nachtblau-huelle-rand, rgba(255, 255, 255, 0.05)); box-shadow: 0 18px 44px -22px var(--nachtblau-schatten, rgba(0, 0, 0, 0.7)); color: var(--nachtblau-text, var(--primary-text-color, #f2f5f8)); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
        .kopf { display: flex; align-items: center; gap: 14px; margin-bottom: 12px; }
        .kachel { width: 44px; height: 44px; border-radius: 13px; display: grid; place-items: center; flex: none; background: color-mix(in srgb, var(--nachtblau-rose, #e6a0c4) 16%, transparent); border: 1px solid color-mix(in srgb, var(--nachtblau-rose, #e6a0c4) 24%, transparent); }
        .kachel ha-icon { --mdc-icon-size: 23px; --ha-icon-display: block; color: var(--nachtblau-rose, #e6a0c4); }
        h2 { margin: 0; font-size: 17px; font-weight: 700; letter-spacing: -0.02em; }
        .unter, .hinweis { font-size: 12.5px; color: var(--nachtblau-text-sekundaer, var(--secondary-text-color, #8794a5)); }
        .hinweis { margin: 8px 0; line-height: 1.45; }
        select { all: unset; box-sizing: border-box; max-width: 100%; cursor: pointer; font-size: 12.5px; color: var(--nachtblau-text-sekundaer, #8794a5); text-decoration: underline dotted; }
        .werte { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
        @container (min-width: 560px) { .werte { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
        .wrap { container-type: inline-size; }
        .wert { background: var(--nachtblau-unterkachel, rgba(255, 255, 255, 0.028)); border: 1px solid var(--nachtblau-unterkachel-rand, rgba(255, 255, 255, 0.06)); border-radius: 14px; padding: 10px 12px; min-width: 0; }
        .wert .l { font-size: 11px; font-weight: 600; color: var(--nachtblau-text-sekundaer, #8794a5); }
        .wert .w { font-size: 17px; font-weight: 700; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; margin-top: 2px; white-space: nowrap; }
        .wert .w small { font-size: 0.62em; color: var(--nachtblau-text-sekundaer, #8794a5); font-weight: 600; margin-left: 3px; }
        .wert .z { font-size: 11px; color: var(--nachtblau-text-sekundaer, #8794a5); margin-top: 2px; }
        .abschnitt { margin-top: 16px; }
        .zeile { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
        h3 { margin: 0; font-size: 13px; font-weight: 700; }
        .schalter { display: inline-flex; background: var(--nachtblau-flaeche-vertieft, #10151d); border: 1px solid var(--nachtblau-unterkachel-rand, rgba(255, 255, 255, 0.06)); border-radius: 12px; padding: 3px; gap: 3px; }
        .schalter button { all: unset; cursor: pointer; font-size: 12px; font-weight: 600; color: var(--nachtblau-text-sekundaer, #8794a5); padding: 5px 11px; border-radius: 9px; }
        .schalter button[aria-pressed="true"] { background: var(--nachtblau-flaeche-erhoeht, #222b3c); color: var(--nachtblau-text, #f2f5f8); }
        .karte { position: relative; z-index: 0; isolation: isolate; height: 300px; border-radius: 14px; overflow: hidden; border: 1px solid var(--nachtblau-unterkachel-rand, rgba(255, 255, 255, 0.06)); background: var(--nachtblau-flaeche-vertieft, #10151d); }
        .legende { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 11.5px; color: var(--nachtblau-text-sekundaer, #8794a5); margin-top: 8px; font-variant-numeric: tabular-nums; }
        .legende span { display: inline-flex; align-items: center; gap: 6px; }
        .legende i { width: 16px; height: 6px; border-radius: 3px; display: inline-block; }
        .legende .notiz { flex-basis: 100%; }
        .anzeige { font-size: 12.5px; color: var(--nachtblau-label, #b4c0cf); font-variant-numeric: tabular-nums; min-height: 18px; margin: 4px 0 6px; }
        .anzeige b { color: var(--nachtblau-text, #f2f5f8); }
        .diagramm .t { font-size: 11px; font-weight: 600; color: var(--nachtblau-text-sekundaer, #8794a5); margin: 8px 0 4px 2px; }
        .diagramm svg { display: block; width: 100%; touch-action: none; }
        .achse { fill: var(--nachtblau-text-sekundaer, #8794a5); font-size: 10.5px; font-variant-numeric: tabular-nums; }
        .gitter { stroke: var(--nachtblau-unterkachel-rand, rgba(255, 255, 255, 0.06)); stroke-dasharray: 3 3; }
        table { width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        th { font-size: 11px; font-weight: 600; color: var(--nachtblau-text-sekundaer, #8794a5); text-align: right; padding: 6px 4px; border-bottom: 1px solid var(--nachtblau-unterkachel-rand, rgba(255, 255, 255, 0.06)); }
        td { text-align: right; padding: 8px 4px; border-bottom: 1px solid var(--nachtblau-unterkachel-rand, rgba(255, 255, 255, 0.06)); }
        th:first-child, td:first-child { text-align: left; }
        td small { color: var(--nachtblau-text-sekundaer, #8794a5); }
        .marke { background: var(--nachtblau-flaeche-erhoeht, #222b3c); color: var(--nachtblau-text, #f2f5f8); border: 1px solid var(--nachtblau-unterkachel-rand, rgba(255, 255, 255, 0.06)); border-radius: 8px; font: 600 11px/1.3 -apple-system, system-ui, sans-serif; padding: 4px 6px; width: max-content; max-width: 150px; text-align: center; box-shadow: 0 4px 10px -4px rgba(0, 0, 0, 0.7); transform: translate(-50%, -140%); display: inline-block; }
        .marke .teil { white-space: nowrap; }
        .leaflet-container { background: var(--nachtblau-flaeche-vertieft, #10151d); font-family: inherit; }
        .dunkel .kachel-dunkel { filter: invert(1) hue-rotate(180deg) brightness(0.82) contrast(0.9) saturate(0.5); }
        .leaflet-control-attribution { background: rgba(16, 21, 29, 0.8) !important; color: var(--nachtblau-text-sekundaer, #8794a5) !important; font-size: 10px; }
        .leaflet-control-attribution a { color: var(--nachtblau-label, #b4c0cf) !important; }
      </style>
      <ha-card><div class="wrap" id="inhalt"></div></ha-card>`;
  }

  _render() {
    const root = this.shadowRoot?.getElementById("inhalt");
    if (!root || !this._hass) return;
    // Alte Leaflet-Karte abbauen, solange ihr Container noch im Dokument ist
    this._removeMap();
    if (this._error) { root.innerHTML = `<div class="hinweis">${this._t("noEntry")}</div>`; return; }
    if (!this._workouts) { root.innerHTML = `<div class="hinweis">${this._t("loading")}</div>`; return; }
    if (!this._summary) { root.innerHTML = `<div class="hinweis">${this._t("none")}</div>`; return; }
    const s = this._summary;
    const start = Date.parse(s.start) / 1000, end = s.end ? Date.parse(s.end) / 1000 : null;
    const date = new Date(start * 1000).toLocaleDateString(this._locale(), { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric", timeZone: this._hass.config?.time_zone });
    const options = (this._workouts || []).map((w) => {
      const d = new Date(Date.parse(w.start)).toLocaleDateString(this._locale(), { day: "2-digit", month: "2-digit", timeZone: this._hass.config?.time_zone });
      const km = w.distance_km != null ? ` · ${this._num(w.distance_km, 2)} km` : "";
      return `<option value="${this._escape(w.id)}" ${w.id === this._current ? "selected" : ""}>${d} · ${this._escape(w.name)}${km}</option>`;
    }).join("");
    const pts = this._points;
    const gps = pts.length ? pts[pts.length - 1].d / 1000 : null;
    const pace = s.pace_s_per_km;
    const tiles = [
      [this._t("distance"), this._num(s.distance_km, 2), "km", gps != null ? `${this._t("gpsRoute")} ${this._num(gps, 2)} km` : ""],
      [this._t("active"), this._duration(s.duration_s), "", `${this._t("total")} ${this._duration(s.elapsed_s)}${s.pause_s ? ` · ${this._t("pause")} ${this._duration(s.pause_s)}` : ""}`],
      [this._t("speed"), this._num(s.speed_kmh, 1), "km/h", pace ? `${this._duration(pace)} ${this._t("perKm")}` : ""],
      [this._t("hrAvg"), this._num(s.hr_avg), "bpm", `${this._t("min")} ${this._num(s.hr_min)} · ${this._t("max")} ${this._num(s.hr_max)}`],
      [this._t("energy"), this._num(s.active_kcal), "kcal", s.total_kcal != null ? `${this._t("total")} ${this._num(s.total_kcal)} kcal` : ""],
      [this._t("effort"), this._num(s.effort), "/ 10", `${this._t("appleEffort")}${s.intensity_met != null ? ` · ${this._num(s.intensity_met, 1)} MET` : ""}`],
      [this._t("elevation"), this._num(s.elevation_up_m), "m", ""],
      [this._t("cadence"), this._num(s.cadence_spm), "/min", [s.temperature_c != null ? `${this._num(s.temperature_c)} °C` : "", s.humidity_pct != null ? `${this._num(s.humidity_pct)} % ${this._t("humidity")}` : ""].filter(Boolean).join(" · ")],
    ];
    const hasRoute = pts.length > 1;
    const hasHr = (this._detail?.heart_rate || []).length > 0;
    root.innerHTML = `
      <div class="kopf">
        <span class="kachel"><ha-icon icon="mdi:walk"></ha-icon></span>
        <div style="min-width:0">
          <h2>${this._escape(s.name || this._t("title"))}</h2>
          <div class="unter">${date} · ${this._clock(start)}${end ? `–${this._clock(end)}` : ""}${options && this._workouts.length > 1 ? ` · <select aria-label="${this._t("title")}">${options}</select>` : ""}</div>
        </div>
      </div>
      <div class="werte">${tiles.map(([l, w, u, z]) => `<div class="wert"><div class="l">${l}</div><div class="w">${w}<small>${u}</small></div><div class="z">${z}</div></div>`).join("")}</div>
      ${!this._detail ? `<div class="hinweis">${this._t("pruned")}</div>` : ""}
      ${hasRoute ? `
      <div class="abschnitt">
        <div class="zeile"><h3>${this._t("route")}</h3>
          <div class="schalter" role="group" aria-label="${this._t("colorBy")}">
            <button type="button" data-m="speed" aria-pressed="${this._colorBy === "speed"}">${this._t("byspeed")}</button>
            ${hasHr ? `<button type="button" data-m="heart_rate" aria-pressed="${this._colorBy === "heart_rate"}">${this._t("byhr")}</button>` : ""}
          </div>
        </div>
        <div class="karte ${this._hass.themes?.darkMode === false ? "" : "dunkel"}" id="karte"></div>
        <div class="legende" id="legende"></div>
      </div>` : ""}
      ${this._detail && (hasRoute || hasHr) ? `
      <div class="abschnitt">
        <h3>${this._t("course")}</h3>
        <div class="anzeige" id="anzeige">${this._t("hint")}</div>
        ${hasHr ? `<div class="diagramm"><div class="t">${this._t("hrChart")}</div><svg id="dHr" height="140"></svg></div>` : ""}
        ${hasRoute ? `<div class="diagramm"><div class="t">${this._t("speedChart")}</div><svg id="dSpeed" height="120"></svg></div>` : ""}
      </div>` : ""}
      ${(this._detail?.splits || []).length ? `
      <div class="abschnitt">
        <h3 style="margin-bottom:6px">${this._t("splits")}</h3>
        <table><thead><tr><th>${this._t("section")}</th><th>${this._t("time")}</th><th>${this._t("pace")}</th><th>${this._t("hrAvgShort")}</th><th>${this._t("hrMaxShort")}</th></tr></thead>
        <tbody>${this._splitRows()}</tbody></table>
      </div>` : ""}`;
    root.querySelector("select")?.addEventListener("change", (e) => { this._selected = e.target.value; this._loadWorkout(e.target.value); });
    root.querySelectorAll(".schalter button").forEach((b) => b.addEventListener("click", () => {
      this._colorBy = b.dataset.m;
      root.querySelectorAll(".schalter button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      this._drawRoute();
    }));
    this._charts = [];
    if (hasRoute) this._initMap(root.querySelector("#karte"));
    this._initCharts(root);
  }

  _removeMap() {
    if (this._resize) { this._resize.disconnect(); this._resize = null; }
    if (this._map) { this._map.remove(); this._map = null; }
    this._dots = null; this._marks = null; this._labelLayer = null; this._routeLayer = null; this._pointer = null; this._ll = null;
  }

  _escape(text) {
    return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  _splitRows() {
    let sum = 0;
    return this._detail.splits.map((sp) => {
      const from = sum / 1000;
      sum += sp.distance_m || 0;
      const to = sum / 1000;
      const pace = sp.distance_m ? sp.active_s / (sp.distance_m / 1000) : null;
      return `<tr><td>${this._num(from, 0)}–${this._num(to, Number.isInteger(Math.round(to * 1000) / 1000) ? 0 : 2)} km</td><td>${this._duration(sp.active_s)}</td><td>${pace ? `${this._duration(pace)} <small>${this._t("perKm")}</small>` : "–"}<br><small>${this._num(sp.speed_kmh, 1)} km/h</small></td><td>${this._num(sp.hr_avg)}</td><td>${this._num(sp.hr_max)}</td></tr>`;
    }).join("");
  }

  _scale() {
    const scale = SCALES[this._colorBy];
    const { limits, relative } = workoutLimits(this._points.map((p) => p[scale.field]), this._colorBy);
    return { ...scale, limits, relative, colors: scale.ramp.map((role) => this._color(role)) };
  }

  _level(scale, value) {
    if (value == null) return -1;
    let i = 0;
    while (i < scale.limits.length && value >= scale.limits[i]) i++;
    return i;
  }

  async _initMap(element) {
    if (!element) return;
    let L;
    try { L = await loadLeaflet(); } catch (err) { element.innerHTML = `<div class="hinweis" style="padding:12px">Leaflet: ${this._t("noData")}</div>`; return; }
    // Waehrend Leaflet lud, kann schon neu gezeichnet worden sein
    if (!element.isConnected) return;
    this._removeMap();
    const map = L.map(element, { scrollWheelZoom: false, attributionControl: true });
    this._map = map;
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      className: "kachel-dunkel",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>',
    }).addTo(map);
    const ll = this._points.map((p) => [p.lat, p.lon]);
    map.fitBounds(L.latLngBounds(ll).pad(0.08));
    // Abschnitte zwischen Luecken (Pausen) getrennt
    this._parts = [];
    let part = [0];
    for (let i = 1; i < this._points.length; i++) {
      if (this._points[i].t - this._points[i - 1].t > 10) { this._parts.push(part); part = [i]; } else part.push(i);
    }
    this._parts.push(part);
    const surface = this._color("surface");
    L.layerGroup(this._parts.map((ix) => L.polyline(ix.map((i) => ll[i]), { color: surface, weight: 8, opacity: 0.9, interactive: false }))).addTo(map);
    this._ll = ll;
    this._drawRoute();
    this._labels();
    map.on("zoomend", () => this._labels());
    this._pointer = L.circleMarker(ll[0], { radius: 7, color: surface, weight: 3, fillColor: this._color("text"), fillOpacity: 0, opacity: 0, interactive: false }).addTo(map);
    map.on("mousemove click", (e) => {
      const target = map.latLngToContainerPoint(e.latlng);
      let best = -1, bestDist = Infinity;
      for (let i = 0; i < ll.length; i += 2) {
        const q = map.latLngToContainerPoint(ll[i]);
        const d = (q.x - target.x) ** 2 + (q.y - target.y) ** 2;
        if (d < bestDist) { bestDist = d; best = i; }
      }
      if (bestDist < 22 * 22) this._show(best);
    });
    this._resize = new ResizeObserver(() => { map.invalidateSize(); this._charts.forEach((c) => c.draw()); });
    this._resize.observe(element);
  }

  _drawRoute() {
    const L = window.L;
    if (!L || !this._map || !this._ll) return;
    if (this._routeLayer) this._map.removeLayer(this._routeLayer);
    const scale = this._scale();
    const field = scale.field;
    const off = this._color("off");
    const lines = [];
    for (const ix of this._parts) {
      let s = ix[0], level = this._level(scale, this._points[s][field]);
      for (let j = 1; j <= ix.length; j++) {
        const i = ix[j];
        const next = i == null ? null : this._level(scale, this._points[i][field]);
        if (i == null || next !== level) {
          const to = i == null ? ix[ix.length - 1] : i;
          const seg = this._ll.slice(s, to + 1);
          if (seg.length > 1) lines.push(L.polyline(seg, { color: level < 0 ? off : scale.colors[level], weight: 5, opacity: 1, lineCap: "round", lineJoin: "round", interactive: false }));
          s = to; level = next;
        }
      }
    }
    this._routeLayer = L.layerGroup(lines).addTo(this._map);
    if (this._dots) this._dots.forEach((d) => d.bringToFront());
    if (this._pointer) this._pointer.bringToFront();
    const fmt = (x) => this._num(x, scale.digits);
    const l = scale.limits;
    const texts = [
      this._colorBy === "speed" ? this._t("stop") : `${this._t("below")} ${fmt(l[0])}`,
      `${fmt(l[0])}–${fmt(l[1])}`, `${fmt(l[1])}–${fmt(l[2])}`, `${fmt(l[2])}–${fmt(l[3])}`, `${this._t("from")} ${fmt(l[3])}`,
    ];
    const legend = this.shadowRoot.getElementById("legende");
    const note = scale.relative ? `<span class="notiz">${this._t(this._colorBy === "speed" ? "levelsSpeed" : "levelsHr")}</span>` : "";
    if (legend) legend.innerHTML = `<span style="color:var(--nachtblau-label, #b4c0cf);font-weight:600">${this._t(this._colorBy === "speed" ? "byspeed" : "byhr")} · ${scale.unit}</span>` + texts.map((t, i) => `<span><i style="background:${scale.colors[i]}"></i>${t}</span>`).join("") + note;
  }

  // Start, Ziel, Kilometer, Pausen, hoechster Minutenpuls; nahe Marken zusammengefasst
  _labels() {
    const L = window.L, map = this._map;
    if (!L || !map) return;
    if (this._labelLayer) map.removeLayer(this._labelLayer);
    if (!this._dots) {
      const marks = [];
      const p = this._points;
      marks.push([0, `${this._t("start")} ${this._clock(p[0].t)}`]);
      marks.push([p.length - 1, `${this._t("finish")} ${this._clock(p[p.length - 1].t)}`]);
      const f = this._dFactor || 1;
      for (let km = 1; km * 1000 < p[p.length - 1].d * f; km++) marks.push([p.findIndex((x) => x.d * f >= km * 1000), `${km} km`]);
      for (const [a, b] of this._detail?.pauses || []) {
        let i = p.findIndex((x) => x.t >= a);
        if (i < 0) i = p.length - 1;
        marks.push([Math.max(0, i - 1), `${this._t("pause")} ${this._duration(b - a)}`]);
      }
      const hr = this._detail?.heart_rate || [];
      if (hr.length) {
        const peak = hr.reduce((a, b) => (b[2] > a[2] ? b : a));
        const i = p.findIndex((x) => x.t >= peak[0] + 30);
        if (i > 0) marks.push([i, `${this._t("hrPeak")} ${this._num(peak[2])}`]);
      }
      this._marks = marks;
      this._dots = marks.map(([i]) => L.circleMarker(this._ll[i], { radius: 4, color: this._color("surface"), weight: 2, fillColor: this._color("text"), fillOpacity: 1, interactive: false }).addTo(map));
    }
    const groups = [];
    for (const [i, text] of this._marks) {
      const q = map.latLngToContainerPoint(this._ll[i]);
      const g = groups.find((x) => Math.hypot(x.x - q.x, x.y - q.y) < 40);
      if (g) g.texts.push(text); else groups.push({ x: q.x, y: q.y, i, texts: [text] });
    }
    this._labelLayer = L.layerGroup(groups.map((g) => L.marker(this._ll[g.i], { interactive: false, icon: L.divIcon({ className: "", html: `<span class="marke">${g.texts.map((t) => `<span class="teil">${t}</span>`).join(" · ")}</span>`, iconSize: [0, 0] }) }))).addTo(map);
  }

  _initCharts(root) {
    const pts = this._points;
    const t0 = Date.parse(this._summary.start) / 1000;
    const t1 = this._summary.end ? Date.parse(this._summary.end) / 1000 : (pts.length ? pts[pts.length - 1].t : t0 + 60);
    const pauses = this._detail?.pauses || [];
    const make = (svg, cfg) => {
      if (!svg) return;
      const chart = { svg, cfg };
      chart.draw = () => {
        const H = +svg.getAttribute("height"), m = { l: 34, r: 8, t: 8, b: 20 };
        const W = svg.clientWidth || 320;
        const x = (t) => m.l + ((t - t0) / Math.max(1, t1 - t0)) * (W - m.l - m.r);
        const [y0, y1] = cfg.dom;
        const y = (v) => m.t + (1 - (v - y0) / Math.max(1e-6, y1 - y0)) * (H - m.t - m.b);
        chart.x = x; chart.y = y;
        let s = "";
        cfg.ticks.forEach((v) => { s += `<line class="gitter" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text class="achse" x="${m.l - 6}" y="${y(v) + 3.5}" text-anchor="end">${this._num(v)}</text>`; });
        const step = (t1 - t0) > 7200 ? 1800 : 900;
        for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) s += `<text class="achse" x="${x(t)}" y="${H - 5}" text-anchor="middle">${this._clock(t)}</text>`;
        pauses.forEach(([a, b]) => { s += `<rect x="${x(a)}" y="${m.t}" width="${Math.max(0, x(b) - x(a))}" height="${H - m.t - m.b}" fill="rgba(255,255,255,.04)"/><text class="achse" x="${(x(a) + x(b)) / 2}" y="${m.t + 11}" text-anchor="middle">${this._t("pause")}</text>`; });
        s += cfg.marks(x, y);
        s += `<line data-k y1="${m.t}" y2="${H - m.b}" stroke="${this._color("muted")}" stroke-width="1" opacity="0"/><circle data-p r="4.5" fill="${this._color("text")}" stroke="${this._color("surface")}" stroke-width="2" opacity="0"/>`;
        s += `<rect data-hit x="${m.l}" y="0" width="${Math.max(0, W - m.l - m.r)}" height="${H}" fill="transparent"/>`;
        svg.innerHTML = s;
        const hit = svg.querySelector("[data-hit]");
        const move = (e) => {
          const r = svg.getBoundingClientRect();
          const px = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
          const t = t0 + ((px - m.l) / Math.max(1, W - m.l - m.r)) * (t1 - t0);
          this._showTime(Math.max(t0, Math.min(t1, t)));
        };
        hit.addEventListener("pointermove", move);
        hit.addEventListener("pointerdown", move);
      };
      chart.draw();
      this._charts.push(chart);
    };
    // Linie fuer zusammenhaengende Abschnitte, Punkt fuer einzelne Werte
    const line = (rows, x, y, color) => {
      const runs = splitRuns(rows, GAP_S);
      const d = runs.filter((r) => r.length > 1).map((r) => r.map(([t, v], i) => (i ? "L" : "M") + x(t).toFixed(1) + "," + y(v).toFixed(1)).join("")).join("");
      const dots = runs.filter((r) => r.length === 1).map(([[t, v]]) => `<circle cx="${x(t).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.5" fill="${color}"/>`).join("");
      return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>${dots}`;
    };
    const hr = this._detail?.heart_rate || [];
    if (hr.length) {
      const lo = Math.floor(Math.min(...hr.map((r) => r[1])) / 10) * 10, hi = Math.ceil(Math.max(...hr.map((r) => r[3])) / 10) * 10;
      const ticks = []; for (let v = lo; v <= hi; v += 10) ticks.push(v);
      const color = this._color("hr");
      const mid = hr.length > 1 && hr[1][0] - hr[0][0] >= 30 ? 30 : 0;
      make(root.querySelector("#dHr"), {
        dom: [lo, Math.max(hi, lo + 10)], ticks, value: (t) => this._hrAt(t),
        marks: (x, y) => {
          let band = "", seg = [];
          const flush = () => { if (seg.length > 1) band += `<path d="M${seg.map((q) => `${x(q[0] + mid).toFixed(1)},${y(q[3]).toFixed(1)}`).join("L")}L${seg.slice().reverse().map((q) => `${x(q[0] + mid).toFixed(1)},${y(q[1]).toFixed(1)}`).join("L")}Z" fill="${mix(color, this._color("surface"), 0.25)}" opacity="0.8"/>`; seg = []; };
          hr.forEach((q, i) => { if (i && q[0] - hr[i - 1][0] > GAP_S) flush(); seg.push(q); });
          flush();
          return band + line(hr.map((q) => [q[0] + mid, q[2]]), x, y, color);
        },
      });
    }
    if (pts.length > 1) {
      const top = Math.max(5, Math.ceil(Math.max(...pts.map((p) => p.v || 0))));
      const ticks = []; for (let v = 0; v <= top; v += top > 8 ? 2 : 1) ticks.push(v);
      const step = Math.max(1, Math.floor(pts.length / 1200));
      make(root.querySelector("#dSpeed"), {
        dom: [0, top], ticks, value: (t) => this._points[this._nearest(t)]?.v,
        marks: (x, y) => line(pts.filter((p, i) => i % step === 0).map((p) => [p.t, p.v]), x, y, this._color("speed")),
      });
    }
  }

  _hrAt(t) {
    const hr = this._detail?.heart_rate || [];
    let best = null;
    for (const row of hr) { if (row[0] <= t) best = row; else break; }
    return best && t - best[0] < 120 ? best[2] : null;
  }

  _nearest(t) {
    const p = this._points;
    let lo = 0, hi = p.length - 1;
    if (hi < 0) return -1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (p[m].t < t) lo = m; else hi = m; }
    return Math.abs(p[lo].t - t) <= Math.abs(p[hi].t - t) ? lo : hi;
  }

  _show(i) {
    this._showTime(this._points[i].t, i);
  }

  _showTime(t, index) {
    const i = index ?? this._nearest(t);
    const p = i >= 0 ? this._points[i] : null;
    const at = p && Math.abs(p.t - t) <= 15 ? p : null;
    if (at && this._pointer) { this._pointer.setLatLng([at.lat, at.lon]).setStyle({ opacity: 1, fillOpacity: 1 }); this._pointer.bringToFront(); }
    for (const c of this._charts) {
      const k = c.svg.querySelector("[data-k]"), dot = c.svg.querySelector("[data-p]");
      if (!k || !dot) continue;
      const xx = c.x(at ? at.t : t);
      k.setAttribute("x1", xx); k.setAttribute("x2", xx); k.setAttribute("opacity", 1);
      const v = c.cfg.value(at ? at.t : t);
      if (v != null) { dot.setAttribute("cx", xx); dot.setAttribute("cy", c.y(Math.max(c.cfg.dom[0], Math.min(c.cfg.dom[1], v)))); dot.setAttribute("opacity", 1); } else dot.setAttribute("opacity", 0);
    }
    const out = this.shadowRoot.getElementById("anzeige");
    if (!out) return;
    const hr = this._hrAt(at ? at.t : t);
    out.innerHTML = `<b>${this._clock(at ? at.t : t, true)}</b>` +
      (at ? ` · ${this._num((at.d * (this._dFactor || 1)) / 1000, 2)} km · ${this._t("byspeed")} <b>${this._num(at.v, 1)} km/h</b>` : "") +
      ` · ${this._t("byhr")} <b>${this._num(hr)}</b> bpm` +
      (at && at.alt != null ? ` · ${this._t("height")} ${this._num(at.alt)} m` : "");
  }
}

if (!customElements.get("ha-training-card")) {
  customElements.define("ha-training-card", HaTrainingCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "ha-training-card",
    name: "Training",
    description: "Training der Apple Watch: Kennzahlen, Route nach Tempo oder Puls, Verlauf und Kilometer.",
    preview: false,
  });
}
