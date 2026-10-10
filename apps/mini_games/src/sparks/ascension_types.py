"""Ascension Types: the labels an Ascended carries, from the Ascension game.

For now a type only filters and groups the collection; it has no effect in battle.
An Ascended holds zero or more of them.
"""

from __future__ import annotations

from enum import StrEnum


class AscensionType(StrEnum):
    PURE = "pure"
    ABYSS = "abyss"  # Dark
    DIVINE = "divine"  # Light
    CRIMSON = "crimson"  # Blood
    ENCHANT = "enchant"  # Elemental
    SYNTHETIC = "synthetic"  # Cyborg, Silicon

    @property
    def label(self) -> str:
        return self.value.capitalize()

    @classmethod
    def parse_all(cls, raw: object, where: str) -> tuple["AscensionType", ...]:
        """A list of known, distinct type ids, in the order given. Raises ValueError otherwise."""
        if not isinstance(raw, list):
            raise ValueError(f"{where}: ascension_types must be a list")
        types: list[AscensionType] = []
        for item in raw:
            try:
                kind = cls(item)
            except ValueError:
                raise ValueError(f"{where}: ascension_types has unknown type {item!r}") from None
            if kind in types:
                raise ValueError(f"{where}: ascension_types lists {kind.value!r} twice")
            types.append(kind)
        return tuple(types)
