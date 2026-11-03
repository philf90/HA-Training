"""Langzeitstatistik der Trainings (E3): Woche, Monat, Jahr, rueckwirkend richtig.

Externe Statistiken des Recorders (``ha_training:distance`` usw.), stuendlich
nach dem Beginn jedes Trainings. Anders als die Wochensensoren landen so auch
Nachzuegler (ein Training vom Sonntag, das erst am Montag ankommt) in der
richtigen Woche, und Loeschen nimmt ein Training auch aus vergangenen Monaten
heraus. Anzeigen lassen sie sich mit den Karten "Statistik" und
"Statistik-Diagramm" (Zeitraum Monat oder Jahr, Wert "Aenderung").

Bei jeder Aenderung wird die ganze Reihe neu geschrieben: erst geloescht,
dann aus allen gespeicherten Zusammenfassungen neu aufgebaut. Der Recorder
arbeitet seine Aufgaben der Reihe nach ab, das Loeschen kommt also vor dem
Schreiben. Das ist einfacher und sicherer als einzelne Stunden zu
korrigieren; auch tausend Trainings sind nur tausend Zeilen je Reihe.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .parser import parse_time
from .sport import CYCLING, FOOT, SWIMMING, sport_of

if TYPE_CHECKING:
    from .storage import TrainingStore

_LOGGER = logging.getLogger(__name__)

# Mehrere Aufrufe kurz hintereinander (Health Auto Export mit Batch Requests)
# loesen nur einen Neuaufbau aus
COOLDOWN_S = 10


def _sum_of(field: str, factor: float = 1, sport: str | None = None):
    def value(workout: dict[str, Any]) -> float | None:
        if sport is not None and sport_of(workout.get("name")) != sport:
            return None
        number = workout.get(field)
        return number * factor if isinstance(number, (int, float)) else None

    return value


# Schluessel -> (Name de, Name en, Einheit, Einheitenklasse, Wert je Training)
# Aktive Energie ohne Einheitenklasse: sonst boete das Energie-Dashboard die
# Reihe als Stromverbrauch an.
SERIES: dict[str, tuple[str, str, str | None, str | None, Callable]] = {
    "workouts": ("Training Anzahl", "Training count", None, None, lambda w: 1.0),
    "distance": (
        "Training Distanz",
        "Training distance",
        "km",
        "distance",
        _sum_of("distance_km"),
    ),
    "duration": (
        "Training Trainingszeit",
        "Training time",
        "min",
        "duration",
        _sum_of("duration_s", 1 / 60),
    ),
    "active_energy": (
        "Training aktive Energie",
        "Training active energy",
        "kcal",
        None,
        _sum_of("active_kcal"),
    ),
    "distance_foot": (
        "Training Distanz zu Fuß",
        "Training distance on foot",
        "km",
        "distance",
        _sum_of("distance_km", sport=FOOT),
    ),
    "distance_cycling": (
        "Training Distanz Radfahren",
        "Training cycling distance",
        "km",
        "distance",
        _sum_of("distance_km", sport=CYCLING),
    ),
    "distance_swimming": (
        "Training Distanz Schwimmen",
        "Training swimming distance",
        "km",
        "distance",
        _sum_of("distance_km", sport=SWIMMING),
    ),
}


def statistic_id(key: str) -> str:
    return f"{DOMAIN}:{key}"


def build(workouts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Stundenzeilen mit laufender Summe je Reihe.

    Je Stunde, in der ein Training beginnt, eine Zeile; davor eine Zeile mit
    Summe 0, damit auch der erste Zeitraum eine Aenderung hat. Reihen ohne
    Wert (z. B. nie geschwommen) bleiben leer.
    """
    hours: dict[str, dict[datetime, float]] = {key: {} for key in SERIES}
    for workout in workouts:
        start = parse_time(workout.get("start"))
        if start is None:
            continue
        hour = dt_util.as_utc(start).replace(minute=0, second=0, microsecond=0)
        for key, (*_, value_fn) in SERIES.items():
            value = value_fn(workout)
            if value is None or value < 0:
                continue
            hours[key][hour] = hours[key].get(hour, 0.0) + value
    result: dict[str, list[dict[str, Any]]] = {}
    for key, by_hour in hours.items():
        if not by_hour:
            result[key] = []
            continue
        ordered = sorted(by_hour)
        rows = [{"start": ordered[0] - timedelta(hours=1), "sum": 0.0}]
        total = 0.0
        for hour in ordered:
            total += by_hour[hour]
            rows.append({"start": hour, "sum": round(total, 3)})
        result[key] = rows
    return result


async def async_rebuild(hass: HomeAssistant, store: TrainingStore) -> bool:
    """Alle Reihen loeschen und neu schreiben. -> False ohne Recorder."""
    if "recorder" not in hass.config.components:
        return False
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.models import StatisticMeanType
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
    )

    workouts = [dict(w) for w in store.workouts]
    series = await hass.async_add_executor_job(build, workouts)
    german = (hass.config.language or "").startswith("de")
    recorder = get_instance(hass)
    recorder.async_clear_statistics([statistic_id(key) for key in SERIES])
    for key, rows in series.items():
        if not rows:
            continue
        name_de, name_en, unit, unit_class, _ = SERIES[key]
        async_add_external_statistics(
            hass,
            {
                "mean_type": StatisticMeanType.NONE,
                "has_sum": True,
                "name": name_de if german else name_en,
                "source": DOMAIN,
                "statistic_id": statistic_id(key),
                "unit_class": unit_class,
                "unit_of_measurement": unit,
            },
            rows,
        )
    _LOGGER.debug("Statistik neu geschrieben: %s Trainings", len(workouts))
    return True


class StatisticsUpdater:
    """Baut die Statistik nach Aenderungen neu auf, gebuendelt."""

    def __init__(self, hass: HomeAssistant, store: TrainingStore) -> None:
        self._hass = hass
        self._store = store
        self._debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=COOLDOWN_S,
            immediate=False,
            function=self._async_run,
        )

    async def _async_run(self) -> None:
        await async_rebuild(self._hass, self._store)

    @callback
    def schedule(self, *_: Any) -> None:
        self._debouncer.async_schedule_call()

    async def async_run_now(self) -> None:
        """Wartenden Aufruf verwerfen und sofort neu aufbauen."""
        self._debouncer.async_cancel()
        await async_rebuild(self._hass, self._store)

    @callback
    def shutdown(self) -> None:
        self._debouncer.async_shutdown()
