"""Sensoren: letztes Training und Summen der laufenden Woche (Montag bis Sonntag)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength, UnitOfSpeed, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from . import TrainingConfigEntry
from .const import SIGNAL_UPDATED
from .entity import TrainingEntity
from .parser import parse_time
from .storage import TrainingStore

PARALLEL_UPDATES = 0
KCAL = "kcal"
BPM = "bpm"


def week_start(now: datetime) -> datetime:
    """Montag 00:00 Ortszeit der Woche von now."""
    local = dt_util.as_local(now)
    monday = local.date() - timedelta(days=local.weekday())
    return dt_util.start_of_local_day(monday)


# Der Index ist nach dem Text von "start" absteigend sortiert. Mit
# unterschiedlichen UTC-Offsets weicht diese Reihenfolge von der echten um
# hoechstens 26 h ab (UTC-12 bis UTC+14); zwei Tage Abstand reichen also.
SORT_MARGIN = timedelta(days=2)


def week_workouts(store: TrainingStore, now: datetime) -> list[dict[str, Any]]:
    """Trainings ab Montag 00:00; bricht ab, sobald die Liste aelter wird.

    Vorher parste jeder der vier Wochensensoren bei jeder Aktualisierung die
    Startzeit aller Trainings (bei 20 000 Trainings 1,7 s im Event-Loop).
    """
    begin = week_start(now)
    result = []
    for w in store.workouts:
        start = parse_time(w.get("start"))
        if start is None:
            continue
        if start >= begin:
            result.append(w)
        elif start < begin - SORT_MARGIN:
            break
    return result


def _latest(key: str, factor: float = 1) -> Callable[[TrainingStore, datetime], Any]:
    def value(store: TrainingStore, now: datetime) -> Any:
        latest = store.latest
        if latest is None or latest.get(key) is None:
            return None
        return latest[key] * factor

    return value


def _week_sum(key: str, factor: float = 1) -> Callable[[TrainingStore, datetime], Any]:
    def value(store: TrainingStore, now: datetime) -> Any:
        return sum((w.get(key) or 0) for w in week_workouts(store, now)) * factor

    return value


def _latest_start(store: TrainingStore, now: datetime) -> Any:
    latest = store.latest
    return parse_time(latest.get("start")) if latest else None


def _week_count(store: TrainingStore, now: datetime) -> Any:
    return len(week_workouts(store, now))


@dataclass(frozen=True, kw_only=True)
class TrainingSensorDescription(SensorEntityDescription):
    value_fn: Callable[[TrainingStore, datetime], Any]
    week: bool = False


SENSORS: tuple[TrainingSensorDescription, ...] = (
    TrainingSensorDescription(
        key="latest_start",
        translation_key="latest_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_latest_start,
    ),
    TrainingSensorDescription(
        key="latest_distance",
        translation_key="latest_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=2,
        value_fn=_latest("distance_km"),
    ),
    TrainingSensorDescription(
        key="latest_duration",
        translation_key="latest_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=_latest("duration_s", 1 / 60),
    ),
    TrainingSensorDescription(
        key="latest_speed",
        translation_key="latest_speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        suggested_display_precision=1,
        value_fn=_latest("speed_kmh"),
    ),
    TrainingSensorDescription(
        key="latest_heart_rate_avg",
        translation_key="latest_heart_rate_avg",
        native_unit_of_measurement=BPM,
        suggested_display_precision=0,
        value_fn=_latest("hr_avg"),
    ),
    TrainingSensorDescription(
        key="latest_heart_rate_max",
        translation_key="latest_heart_rate_max",
        native_unit_of_measurement=BPM,
        suggested_display_precision=0,
        value_fn=_latest("hr_max"),
    ),
    TrainingSensorDescription(
        key="latest_active_energy",
        translation_key="latest_active_energy",
        native_unit_of_measurement=KCAL,
        suggested_display_precision=0,
        value_fn=_latest("active_kcal"),
    ),
    TrainingSensorDescription(
        key="latest_effort",
        translation_key="latest_effort",
        suggested_display_precision=0,
        value_fn=_latest("effort"),
    ),
    TrainingSensorDescription(
        key="latest_elevation_up",
        translation_key="latest_elevation_up",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=0,
        value_fn=_latest("elevation_up_m"),
    ),
    TrainingSensorDescription(
        key="week_count",
        translation_key="week_count",
        state_class=SensorStateClass.TOTAL,
        value_fn=_week_count,
        week=True,
    ),
    TrainingSensorDescription(
        key="week_distance",
        translation_key="week_distance",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=1,
        value_fn=_week_sum("distance_km"),
        week=True,
    ),
    TrainingSensorDescription(
        key="week_duration",
        translation_key="week_duration",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=_week_sum("duration_s", 1 / 60),
        week=True,
    ),
    TrainingSensorDescription(
        key="week_active_energy",
        translation_key="week_active_energy",
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=KCAL,
        suggested_display_precision=0,
        value_fn=_week_sum("active_kcal"),
        week=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TrainingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(TrainingSensor(entry, description) for description in SENSORS)


class TrainingSensor(TrainingEntity, SensorEntity):
    """Wert aus dem Index der Trainings; aktualisiert bei neuen Trainings."""

    entity_description: TrainingSensorDescription

    def __init__(
        self, entry: TrainingConfigEntry, description: TrainingSensorDescription
    ) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATED}_{self._entry.entry_id}",
                self._handle_update,
            )
        )
        if self.entity_description.week:
            # Neue Woche ab Montag 00:00; taeglich kurz nach Mitternacht reicht.
            self.async_on_remove(
                async_track_time_change(
                    self.hass, self._handle_update, hour=0, minute=0, second=5
                )
            )

    @callback
    def _handle_update(self, *_: Any) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._store, dt_util.now())

    @property
    def last_reset(self) -> datetime | None:
        if self.entity_description.state_class is SensorStateClass.TOTAL:
            return week_start(dt_util.now())
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "latest_start":
            return None
        latest = self._store.latest
        if latest is None:
            return None
        return {
            "workout_id": latest.get("id"),
            "name": latest.get("name"),
            "location": latest.get("location"),
            "end": latest.get("end"),
        }
