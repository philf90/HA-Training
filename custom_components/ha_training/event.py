"""Ereignis "Neues Training", z. B. fuer eine Push-Nachricht mit der Zusammenfassung."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TrainingConfigEntry
from .const import EVENT_NEW_WORKOUT, SIGNAL_UPDATED
from .entity import TrainingEntity
from .parser import parse_time

PARALLEL_UPDATES = 0
# Beim ersten Abgleich schickt Health Auto Export oft Trainings mehrerer Wochen.
# Ausgeloest wird nur fuer Trainings, die hoechstens so lange vorbei sind; die
# aelteren landen trotzdem im Index und in den Sensoren.
MAX_AGE = timedelta(hours=24)
EVENT_KEYS = (
    "name",
    "start",
    "end",
    "distance_km",
    "duration_s",
    "speed_kmh",
    "hr_avg",
    "hr_max",
    "active_kcal",
    "effort",
    "elevation_up_m",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TrainingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NewWorkoutEvent(entry)])


def is_recent(workout: dict[str, Any]) -> bool:
    end = parse_time(workout.get("end")) or parse_time(workout.get("start"))
    return end is not None and dt_util.now() - end <= MAX_AGE


class NewWorkoutEvent(TrainingEntity, EventEntity):
    _attr_translation_key = "new_workout"

    def __init__(self, entry: TrainingConfigEntry) -> None:
        super().__init__(entry, "new_workout")
        self._attr_event_types = [EVENT_NEW_WORKOUT]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATED}_{self._entry.entry_id}",
                self._handle_new,
            )
        )

    @callback
    def _handle_new(self, new: list[dict[str, Any]]) -> None:
        recent = sorted(
            (w for w in new if is_recent(w)), key=lambda w: w.get("start") or ""
        )
        for workout in recent:
            attributes = {key: workout.get(key) for key in EVENT_KEYS}
            attributes["workout_id"] = workout.get("id")
            self._trigger_event(EVENT_NEW_WORKOUT, attributes)
            self.async_write_ha_state()
