"""Basisklasse: alle Entitaeten haengen am Geraet "Training" des Eintrags."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, TITLE

if TYPE_CHECKING:
    from . import TrainingConfigEntry
    from .storage import TrainingStore


class TrainingEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: TrainingConfigEntry, key: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=TITLE,
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Health Auto Export",
            model="Apple Health",
        )

    @property
    def _store(self) -> TrainingStore:
        return self._entry.runtime_data.store
