"""Sportart eines Trainings aus seinem Namen.

Health Auto Export liefert die Sportart nur als Namen (Doku "Workouts":
name = "Workout type name"); einen Code dafuer gibt es nicht. Der Name kommt in
der Sprache des iPhones und mit dem Ort davor, z. B. "Outdoor Spaziergang" oder
"Outdoor Radfahren" (echte Exporte vom 31.10. und 03.11.2026). Erkannt werden
deshalb deutsche und englische Woerter.

Gruppen statt einzelner Sportarten: Die Wochensummen trennen nur, was sich
nicht sinnvoll addieren laesst (Kilometer zu Fuss, auf dem Rad, im Wasser).
Alles andere bleibt "other" und zaehlt nur in den Gesamtsummen.
"""

from __future__ import annotations

import re

FOOT = "foot"
CYCLING = "cycling"
SWIMMING = "swimming"
OTHER = "other"
GROUPS = (FOOT, CYCLING, SWIMMING)

# Teile eines Wortes, egal wo: "Freiwasserschwimmen", "Mountainbike",
# "Hand Cycling"
_SWIM = ("schwimm", "swim")
_CYCLE = ("radfahr", "fahrrad", "cycl", "bike")
# Wortanfaenge: "lauf" als Teil eines Wortes traefe auch "Skilanglauf"
_FOOT = ("lauf", "geh", "spazier", "wander", "jog", "walk", "run", "hik")

# Rollstuhl-Trainings ("Wheelchair Walk Pace") sind nicht zu Fuss
_NOT_FOOT = ("rollstuhl", "wheelchair")

_WORDS = re.compile(r"[^\W\d_]+")


def sport_of(name: object) -> str:
    """foot, cycling, swimming oder other."""
    if not isinstance(name, str):
        return OTHER
    text = name.casefold()
    if any(part in text for part in _SWIM):
        return SWIMMING
    if any(part in text for part in _CYCLE):
        return CYCLING
    if any(part in text for part in _NOT_FOOT):
        return OTHER
    if any(word.startswith(_FOOT) for word in _WORDS.findall(text)):
        return FOOT
    return OTHER
