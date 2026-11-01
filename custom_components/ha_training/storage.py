"""Ablage der Trainings unter .storage/ (privat, nicht ueber /local/ erreichbar).

Ein Index haelt die Zusammenfassungen aller Trainings, neuestes zuerst. Die
Details (Route, Verlaeufe) liegen je Training in einer eigenen Datei, damit der
Index klein bleibt und eine Abfrage der Karte nur ein Training laedt. Details
aelterer Trainings werden nach der Option "keep_details" geloescht; ihre
Zusammenfassung bleibt.

Geloeschte Trainings verschwinden ganz (Zusammenfassung und Details); ihre ID
kommt auf eine Sperrliste im Index, denn Health Auto Export schickt je nach
Zeitraum dieselben Trainings erneut. Erst "wieder annehmen" nimmt sie von der
Liste.

Alle schreibenden Methoden laufen unter einem Lock: Webhook, Optionen und
Loeschen veraendern dieselbe Liste und warten dazwischen auf Dateizugriffe.
"""

from __future__ import annotations

import asyncio
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
        # serialize_in_event_loop=False: Home Assistant erzeugt das JSON dann im
        # Executor statt im Event-Loop (helpers/storage.py, Standard ist True).
        # Erlaubt, weil der Index als Kopie und die Details als frisch geparste,
        # danach unveraenderte Daten uebergeben werden.
        self._index: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_INDEX}.{entry_id}",
            private=True,
            serialize_in_event_loop=False,
        )
        self.workouts: list[dict[str, Any]] = []
        self.deleted: set[str] = set()
        self._lock = asyncio.Lock()

    def _detail_store(self, workout_id: str) -> Store[dict[str, Any]]:
        return Store(
            self._hass,
            STORAGE_VERSION,
            _detail_key(self._entry_id, workout_id),
            private=True,
            serialize_in_event_loop=False,
        )

    async def async_load(self) -> None:
        data = await self._index.async_load() or {}
        workouts = data.get("workouts")
        self.workouts = workouts if isinstance(workouts, list) else []
        deleted = data.get("deleted")
        self.deleted = (
            {d for d in deleted if isinstance(d, str)}
            if isinstance(deleted, list)
            else set()
        )

    async def _async_save_index(self) -> None:
        # Kopie: der Executor serialisiert, waehrend der Event-Loop weiterlaeuft
        await self._index.async_save(
            {
                "workouts": [dict(w) for w in self.workouts],
                "deleted": sorted(self.deleted),
            }
        )

    def get(self, workout_id: str) -> dict[str, Any] | None:
        return next((w for w in self.workouts if w.get("id") == workout_id), None)

    @property
    def latest(self) -> dict[str, Any] | None:
        return self.workouts[0] if self.workouts else None

    async def async_add(
        self, parsed: list[tuple[dict[str, Any], dict[str, Any]]]
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Neue und geaenderte Trainings speichern.

        -> (neue, Anzahl geaendert, Anzahl uebersprungen weil geloescht)

        Health Auto Export schickt je nach Zeitraum dieselben Trainings
        mehrmals; die id von Apple Health macht sie eindeutig. Ein erneut
        geschicktes Training ersetzt das alte nur, wenn sich etwas geaendert hat.
        """
        async with self._lock:
            return await self._async_add(parsed)

    async def _async_add(
        self, parsed: list[tuple[dict[str, Any], dict[str, Any]]]
    ) -> tuple[list[dict[str, Any]], int, int]:
        """In zwei Schritten, damit ein Aufruf mit vielen Trainings linear bleibt.

        1. Zusammenfassungen einordnen; die Suche nach der ID geht ueber ein
           Dict statt durch die Liste (vorher quadratisch: 5000 Trainings
           blockierten den Event-Loop fast 5 s).
        2. Nach dem Sortieren Details nur fuer Trainings innerhalb der
           Aufbewahrung schreiben. Was dahinter liegt, wuerde sonst geschrieben
           und gleich wieder geloescht.
        """
        new: list[dict[str, Any]] = []
        updated = 0
        skipped = 0
        restore: set[str] = set()  # unveraendert, aber ohne Details
        pending: dict[str, dict[str, Any]] = {}
        position = {w.get("id"): i for i, w in enumerate(self.workouts)}
        added: dict[str, int] = {}  # in diesem Aufruf neu -> Stelle in new
        for summary, detail in parsed:
            workout_id = summary["id"]
            if workout_id in self.deleted:
                skipped += 1
                continue
            i = position.get(workout_id)
            if workout_id in added:
                # Dieselbe ID zweimal in einem Aufruf: die letzte Fassung gilt,
                # es bleibt ein neues Training
                entry = {**summary, "has_detail": False}
                self.workouts[i] = entry
                new[added[workout_id]] = entry
                pending[workout_id] = detail
                continue
            if i is None:
                entry = {**summary, "has_detail": False}
                position[workout_id] = len(self.workouts)
                added[workout_id] = len(new)
                self.workouts.append(entry)
                new.append(entry)
                pending[workout_id] = detail
                continue
            old = self.workouts[i]
            unchanged = {k: v for k, v in old.items() if k != "has_detail"} == summary
            if unchanged:
                if old.get("has_detail"):
                    continue
                # Holt fehlende Details zurueck, wenn es in der Aufbewahrung
                # liegt (z. B. nach dem Erhoehen in den Optionen)
                restore.add(workout_id)
            else:
                self.workouts[i] = {
                    **summary,
                    "has_detail": bool(old.get("has_detail")),
                }
                updated += 1
            pending[workout_id] = detail
        if not pending:
            return new, updated, skipped
        self.workouts.sort(key=lambda w: w.get("start") or "", reverse=True)
        kept = {w.get("id"): w for w in self.workouts[: self.keep_details]}
        changed = bool(new) or updated > 0
        for workout_id, detail in pending.items():
            workout = kept.get(workout_id)
            if workout is None:
                continue
            await self._detail_store(workout_id).async_save(detail)
            workout["has_detail"] = True
            if workout_id in restore:
                updated += 1
                changed = True
        if changed:
            await self._async_prune()
            await self._async_save_index()
        return new, updated, skipped

    async def _async_prune(self) -> None:
        """Details aelterer Trainings loeschen, Zusammenfassung behalten."""
        for position, workout in enumerate(self.workouts):
            if position >= self.keep_details and workout.get("has_detail"):
                await self._detail_store(workout["id"]).async_remove()
                workout["has_detail"] = False

    async def async_set_keep_details(self, keep: int) -> None:
        async with self._lock:
            self.keep_details = keep
            await self._async_prune()
            await self._async_save_index()

    async def async_delete(self, workout_id: str) -> dict[str, Any] | None:
        """Training ganz loeschen und seine ID sperren -> geloeschte Zusammenfassung."""
        async with self._lock:
            workout = self.get(workout_id)
            if workout is None:
                return None
            self.workouts.remove(workout)
            self.deleted.add(workout_id)
            # Auch ohne has_detail: eine Datei aus einem abgebrochenen Lauf
            await self._detail_store(workout_id).async_remove()
            await self._async_save_index()
            return workout

    async def async_undelete(self, workout_id: str) -> bool:
        """ID von der Sperrliste nehmen; das naechste Senden legt es neu an."""
        async with self._lock:
            if workout_id not in self.deleted:
                return False
            self.deleted.discard(workout_id)
            await self._async_save_index()
            return True

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
