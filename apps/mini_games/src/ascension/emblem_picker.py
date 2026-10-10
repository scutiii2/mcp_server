"""Choosing an EMBLEM tier for an autonomous CATCH after the player's prompt timed out."""

from __future__ import annotations

from typing import Protocol

from src.laya_client import LayaClient, LayaError
from src.ascension.situation import SituationView

INSTRUCTIONS = "Which EMBLEM tier should this fighter spend on collecting the enemy?"


class EmblemPicker(Protocol):
    async def pick(self, view: SituationView, chances: dict[str, float]) -> str | None:
        """A tier id from `chances` (tier id -> chance to collect now), or None."""


class LayaEmblemPicker:
    def __init__(self, client: LayaClient) -> None:
        self._client = client

    async def pick(self, view: SituationView, chances: dict[str, float]) -> str | None:
        if not chances:
            return None
        if len(chances) == 1:  # nothing to choose between
            return next(iter(chances))
        options = {tier: f"{tier} EMBLEM, {chance:.0%} chance to collect" for tier, chance in chances.items()}
        try:
            answer = await self._client.choose(view.to_text(), INSTRUCTIONS, options)
        except LayaError:
            return None
        return None if answer.uncertain else answer.value
