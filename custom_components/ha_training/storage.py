"""Ablage der Trainings unter .storage/ (privat, nicht ueber /local/ erreichbar).

Ein Index haelt die Zusammenfassungen aller Trainings, neuestes zuerst. Die
Details (Route, Verlaeufe) liegen je Training in einer eigenen Datei, damit der
Index klein bleibt und eine Abfrage der Karte nur ein Training laedt. Details
aelterer Trainings werden nach der Option "keep_details" geloescht; ihre
Zusammenfassung bleibt.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_DETAIL, STORAGE_INDEX, STORAGE_VERSION

_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def _detail_key(entry_id: str, workout_id: str) -> str:
    return f"{STORAGE_DETAIL}.{entry_id}.{_SAFE.sub('_', workout_id)}"


class TrainingStore:
    """Index und Details der Trainings eines Eintrags."""

    def __init__(self, hass: HomeAssistant, entry_id: str, keep_details: int) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self.keep_details = keep_details
        self._index: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_INDEX}.{entry_id}", private=True
        )
        self.workouts: list[dict[str, Any]] = []

    def _detail_store(self, workout_id: str) -> Store[dict[str, Any]]:
        return Store(
            self._hass,
            STORAGE_VERSION,
            _detail_key(self._entry_id, workout_id),
            private=True,
        )

    async def async_load(self) -> None:
        data = await self._index.async_load() or {}
        workouts = data.get("workouts")
        self.workouts = workouts if isinstance(workouts, list) else []

    def get(self, workout_id: str) -> dict[str, Any] | None:
        return next((w for w in self.workouts if w.get("id") == workout_id), None)

    @property
    def latest(self) -> dict[str, Any] | None:
        return self.workouts[0] if self.workouts else None

    async def async_add(
        self, parsed: list[tuple[dict[str, Any], dict[str, Any]]]
    ) -> tuple[list[dict[str, Any]], int]:
        """Neue und geaenderte Trainings speichern -> (neue, Anzahl geaendert).

        Health Auto Export schickt je nach Zeitraum dieselben Trainings
        mehrmals; die id von Apple Health macht sie eindeutig. Ein erneut
        geschicktes Training ersetzt das alte nur, wenn sich etwas geaendert hat.
        """
        new: list[dict[str, Any]] = []
        updated = 0
        for summary, detail in parsed:
            old = self.get(summary["id"])
            if old is None:
                summary = {**summary, "has_detail": True}
                self.workouts.append(summary)
                new.append(summary)
                await self._detail_store(summary["id"]).async_save(detail)
                continue
            position = self.workouts.index(old)
            # Liegt das Training hinter der Aufbewahrung, wuerden seine Details
            # gleich wieder geloescht. Unveraendert: ueberspringen; geaendert:
            # nur die Zusammenfassung ersetzen. Innerhalb der Aufbewahrung holt
            # ein erneut geschicktes Training fehlende Details zurueck.
            keep = position < self.keep_details or bool(old.get("has_detail"))
            unchanged = {k: v for k, v in old.items() if k != "has_detail"} == summary
            if unchanged and (old.get("has_detail") or not keep):
                continue
            summary = {**summary, "has_detail": keep}
            self.workouts[position] = summary
            updated += 1
            if keep:
                await self._detail_store(summary["id"]).async_save(detail)
        if new or updated:
            self.workouts.sort(key=lambda w: w.get("start") or "", reverse=True)
            await self._async_prune()
            await self._index.async_save({"workouts": self.workouts})
        return new, updated

    async def _async_prune(self) -> None:
        """Details aelterer Trainings loeschen, Zusammenfassung behalten."""
        for position, workout in enumerate(self.workouts):
            if position >= self.keep_details and workout.get("has_detail"):
                await self._detail_store(workout["id"]).async_remove()
                workout["has_detail"] = False

    async def async_set_keep_details(self, keep: int) -> None:
        self.keep_details = keep
        await self._async_prune()
        await self._index.async_save({"workouts": self.workouts})

    async def async_get_detail(self, workout_id: str) -> dict[str, Any] | None:
        workout = self.get(workout_id)
        if workout is None or not workout.get("has_detail"):
            return None
        return await self._detail_store(workout_id).async_load()

    async def async_remove_all(self) -> None:
        """Beim Entfernen des Eintrags: Index und alle Details loeschen."""
        await self.async_load()
        for workout in self.workouts:
            await self._detail_store(workout["id"]).async_remove()
        await self._index.async_remove()
        self.workouts = []
