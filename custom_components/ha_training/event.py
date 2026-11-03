"""Ereignisse "Neues Training" und "Neue Bestleistung", z. B. fuer Push-Nachrichten."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TrainingConfigEntry
from .const import EVENT_NEW_RECORD, EVENT_NEW_WORKOUT, SIGNAL_RECORD, SIGNAL_UPDATED
from .entity import TrainingEntity
from .rekorde import is_recent

PARALLEL_UPDATES = 0
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
    async_add_entities([NewWorkoutEvent(entry), NewRecordEvent(entry)])


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


# Einheit je Bestleistung (rekorde.RECORDS), fuer die Nachricht
RECORD_UNITS = {
    "distance": "km",
    "best_km": "s",
    "elevation": "m",
    "streak_longest": "d",
}


class NewRecordEvent(TrainingEntity, EventEntity):
    """Neue Bestleistung durch ein neues Training (E4).

    Attribute: record (z. B. distance_cycling, best_km_foot, streak_longest),
    value, previous, unit und beim Rekord eines Trainings workout_id, name,
    start. Das erste Training einer Sportart loest nichts aus.
    """

    _attr_translation_key = "new_record"

    def __init__(self, entry: TrainingConfigEntry) -> None:
        super().__init__(entry, "new_record")
        self._attr_event_types = [EVENT_NEW_RECORD]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_RECORD}_{self._entry.entry_id}",
                self._handle_records,
            )
        )

    @callback
    def _handle_records(self, records: list[dict[str, Any]]) -> None:
        for record in records:
            key = record["record"]
            unit = next(
                (u for prefix, u in RECORD_UNITS.items() if key.startswith(prefix)),
                None,
            )
            self._trigger_event(EVENT_NEW_RECORD, {**record, "unit": unit})
            self.async_write_ha_state()
