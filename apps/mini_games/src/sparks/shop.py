"""The shop: buy EMBLEMs and regular-Spark copies, sell copies back."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.sparks.catalog import Catalog
from src.sparks.errors import InsufficientFunds, InvalidRequest, NotFound, NothingToSell, WrongPhase
from src.sparks.idempotency import IdempotentWriter
from src.sparks.progression import ProgressionService
from src.sparks.records import SparkRecord
from src.sparks.repository import SparkTransaction

MAX_EMBLEM_PURCHASE = 99


class ShopService:
    def __init__(self, writer: IdempotentWriter, catalog: Catalog, progression: ProgressionService) -> None:
        self._writer, self._catalog, self._progression = writer, catalog, progression

    # -- prices --------------------------------------------------------------------

    def copy_price(self, spark_id: str, owned: SparkRecord | None, tier_id: str) -> tuple[int, int, str]:
        """(price, copies granted, resulting tier) for buying the regular `tier_id` package.
        The price is twice the resale value of the granted copies at the resulting tier and level."""
        granted = self._catalog.tier(tier_id).copy_reward
        copies = (owned.copies if owned else 0) + granted
        resulting = self._catalog.tier_for_copies(spark_id, copies)
        level = owned.level if owned else 1
        per_copy = self._catalog.sale_value(spark_id, resulting, level)
        return self._catalog.economy.purchase_factor * granted * per_copy, granted, resulting

    # -- operations ----------------------------------------------------------------

    @staticmethod
    async def _spend(tx: SparkTransaction, owner: str, price: int) -> None:
        player = await tx.get_player(owner)
        if player is None:
            raise NotFound("no profile yet; choose a starter first")
        if player.insignia < price:
            raise InsufficientFunds(f"that costs {price} Insignia and you have {player.insignia}")
        await tx.add_insignia(owner, -price)

    @staticmethod
    async def _reject_if_fighting(tx: SparkTransaction, owner: str, spark_id: str) -> None:
        battle = await tx.active_battle(owner)
        if battle is not None and battle.setup.player.spark_id == spark_id:
            raise WrongPhase("that Spark is fighting in the active battle")

    async def buy_emblems(self, owner: str, key: str, tier_id: str, quantity: int) -> dict[str, Any]:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= MAX_EMBLEM_PURCHASE:
            raise InvalidRequest(f"quantity must be a whole number from 1 to {MAX_EMBLEM_PURCHASE}")
        tier = self._catalog.tier(tier_id)  # forbidden EMBLEMs are sold too

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            price = tier.emblem_price * quantity
            await self._spend(tx, owner, price)
            await tx.add_emblems(owner, tier_id, quantity)
            return {"kind": "emblems", "tier_id": tier_id, "quantity": quantity, "price": price}

        return await self._writer.commit(owner, key, "shop.emblems", {"tier": tier_id, "quantity": quantity}, work)

    async def buy_copies(self, owner: str, key: str, spark_id: str, tier_id: str) -> dict[str, Any]:
        spec = self._catalog.spark(spark_id)
        if spec.forbidden:
            raise InvalidRequest("the Forbidden Spark can only be captured")
        if self._catalog.tier(tier_id).copy_threshold is None:
            raise InvalidRequest("choose one of the five regular tiers")

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            await self._reject_if_fighting(tx, owner, spark_id)
            owned = await tx.get_spark(owner, spark_id)
            price, granted, resulting = self.copy_price(spark_id, owned, tier_id)
            await self._spend(tx, owner, price)
            if owned is None:
                await tx.put_spark(SparkRecord(owner, spark_id, granted, 1, 0))
            else:
                await tx.put_spark(replace(owned, copies=owned.copies + granted))
            return {"kind": "copies", "spark_id": spark_id, "tier_id": tier_id, "copies_granted": granted,
                    "price": price, "resulting_tier_id": resulting}

        return await self._writer.commit(owner, key, "shop.copies", {"spark": spark_id, "tier": tier_id}, work)

    async def sell_copy(self, owner: str, key: str, spark_id: str) -> dict[str, Any]:
        self._catalog.spark(spark_id)

        async def work(tx: SparkTransaction) -> dict[str, Any]:
            await self._reject_if_fighting(tx, owner, spark_id)
            owned = await tx.get_spark(owner, spark_id)
            if owned is None or owned.copies == 0:
                raise NothingToSell("there is no absorbed copy to sell")
            before = self._catalog.tier_for_copies(spark_id, owned.copies)
            value = self._catalog.sale_value(spark_id, before, owned.level)  # tier and level before the copy goes
            await tx.put_spark(replace(owned, copies=owned.copies - 1))
            await tx.add_insignia(owner, value)
            after = self._catalog.tier_for_copies(spark_id, owned.copies - 1)
            return {"kind": "sale", "spark_id": spark_id, "value": value, "copies": owned.copies - 1,
                    "tier_id": after, "downgraded": after != before}

        return await self._writer.commit(owner, key, "shop.sell", {"spark": spark_id}, work)
