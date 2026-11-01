"""GPX 1.1 aus einem gespeicherten Training (Route mit Hoehe, Zeit und Puls).

Der Puls steht in der Garmin-Erweiterung TrackPointExtension v1 (gpxtpx:hr),
die Strava, Komoot, Garmin Connect und andere lesen. Je Punkt gilt der letzte
Pulswert davor, wenn er hoechstens 120 s alt ist (wie in der Karte). Eine
Luecke von mehr als 10 s zwischen zwei Punkten (Pause, GPS-Ausfall) beginnt ein
neues Segment, damit Programme die Luecke nicht als gerade Linie zeichnen.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape, quoteattr

GAP_S = 10
HR_MAX_AGE_S = 120
NS_GPX = "http://www.topografix.com/GPX/1/1"
NS_TPX = "http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
SCHEMAS = (
    f"{NS_GPX} http://www.topografix.com/GPX/1/1/gpx.xsd "
    f"{NS_TPX} http://www.garmin.com/xmlschemas/TrackPointExtensionv1.xsd"
)
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def _utc(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def filename(summary: dict[str, Any]) -> str:
    """z. B. training-2026-11-01-0945-outdoor-spaziergang.gpx (Ortszeit aus start)."""
    start = str(summary.get("start") or "")[:16].replace("T", "-").replace(":", "")
    name = _UNSAFE_NAME.sub("-", str(summary.get("name") or "").lower()).strip("-")
    return "-".join(p for p in ("training", start, name) if p) + ".gpx"


def build_gpx(summary: dict[str, Any], detail: dict[str, Any]) -> str | None:
    """GPX-Text oder None, wenn das Training keine Route hat."""
    fields = list(detail.get("route_fields") or [])
    route = detail.get("route") or []
    if not route or not {"t", "lat", "lon"} <= set(fields):
        return None
    col = {name: fields.index(name) for name in fields}
    hr_rows = detail.get("heart_rate") or []
    hr_fields = list(detail.get("heart_rate_fields") or [])
    hr_t = hr_fields.index("t") if "t" in hr_fields else 0
    hr_avg = hr_fields.index("avg") if "avg" in hr_fields else 2

    name = str(summary.get("name") or "Training")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<gpx version="1.1" creator="Home Assistant Training" xmlns="{NS_GPX}" '
            f'xmlns:gpxtpx="{NS_TPX}" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            f"xsi:schemaLocation={quoteattr(SCHEMAS)}>"
        ),
        "  <metadata>",
        f"    <name>{escape(name)}</name>",
        f"    <time>{_utc(int(route[0][col['t']]))}</time>",
        "  </metadata>",
        "  <trk>",
        f"    <name>{escape(name)}</name>",
        "    <trkseg>",
    ]
    h = 0
    last_t: int | None = None
    for row in route:
        t, lat, lon = int(row[col["t"]]), row[col["lat"]], row[col["lon"]]
        if last_t is not None and t - last_t > GAP_S:
            lines += ["    </trkseg>", "    <trkseg>"]
        last_t = t
        while h + 1 < len(hr_rows) and hr_rows[h + 1][hr_t] <= t:
            h += 1
        hr = None
        if hr_rows and hr_rows[h][hr_t] <= t and t - hr_rows[h][hr_t] <= HR_MAX_AGE_S:
            hr = hr_rows[h][hr_avg]
        point = [f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}">']
        alt = row[col["alt"]] if "alt" in col else None
        if alt is not None:
            point.append(f"<ele>{alt:.1f}</ele>")
        point.append(f"<time>{_utc(t)}</time>")
        if hr is not None:
            point.append(
                "<extensions><gpxtpx:TrackPointExtension>"
                f"<gpxtpx:hr>{round(hr)}</gpxtpx:hr>"
                "</gpxtpx:TrackPointExtension></extensions>"
            )
        point.append("</trkpt>")
        lines.append("".join(point))
    lines += ["    </trkseg>", "  </trk>", "</gpx>", ""]
    return "\n".join(lines)
