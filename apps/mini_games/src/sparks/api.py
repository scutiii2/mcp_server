"""HTTP routes for Emberlings: thin adapters over the services.

Ownership comes from the trusted requester header only. Request bodies reject
unknown fields, so a client can never supply rewards, stats, chances, random
results or personalities. Every mutation needs an Idempotency-Key header.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt

from src.auth import requester
from src.sparks.catalog import Catalog, CatalogError
from src.sparks.collection import CollectionService
from src.sparks.coordinator import RoundCoordinator
from src.sparks.encounters import EncounterService
from src.sparks.errors import EncounterCooldown, SparkError
from src.sparks.shop import ShopService


@dataclass(frozen=True)
class SparkServices:
    catalog: Catalog
    collection: CollectionService
    encounters: EncounterService
    shop: ShopService
    coordinator: RoundCoordinator


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InitializeBody(_Body):
    starter_species_id: str


class PresetBody(_Body):
    instance_ids: list[str]


class StartBody(_Body):
    encounter_id: str
    species_id: str
    preset_slot: StrictInt | None = None
    mode: str = "manual"
    emblem_limit: str | None = None


class ActionBody(_Body):
    kind: str
    ability_id: str | None = None
    emblem_tier: str | None = None


class RoundBody(_Body):
    round: StrictInt
    revision: StrictInt


class ActionRequest(RoundBody):
    action: ActionBody


class EmblemRequest(RoundBody):
    tier: str


class ModeRequest(RoundBody):
    mode: str
    emblem_limit: str | None = None


class PurchaseBody(_Body):
    kind: str
    tier: str
    quantity: StrictInt = 1
    species_id: str | None = None


def idempotency_key(idempotency_key: str = Header(default="", alias="Idempotency-Key")) -> str:
    if not idempotency_key.strip():
        raise HTTPException(400, "an Idempotency-Key header is required for this request")
    return idempotency_key.strip()


def catalog_summary(catalog: Catalog) -> dict[str, Any]:
    """Public catalog data: species, abilities, tiers, personalities and shop metadata."""
    return {
        "version": catalog.version,
        "tiers": [
            {"id": t.id, "stat_multiplier": t.stat_multiplier, "copy_threshold": t.copy_threshold, "copy_reward": t.copy_reward,
             "emblem_strength": t.emblem_strength, "emblem_price": t.emblem_price}
            for t in catalog.tiers
        ],
        "levels": {"regular_cap": catalog.levels.regular_cap, "forbidden_cap": catalog.levels.forbidden_cap},
        "species": [
            {"id": s.id, "name": s.name, "starter": s.starter, "forbidden": s.forbidden, "base": dict(s.base),
             "growth": dict(s.growth), "base_price": s.base_price, "passive": s.passive.to_dict(),
             "abilities": [a.to_dict() for a in s.abilities]}
            for s in catalog.all_species()
        ],
        "personalities": [{"id": p.id, "categories": list(p.categories)} for p in catalog.personalities.values()],
    }


def build_router(services: SparkServices) -> APIRouter:
    router = APIRouter(prefix="/sparks")
    collection, encounters, shop, coordinator = services.collection, services.encounters, services.shop, services.coordinator

    @router.get("/catalog")
    async def catalog() -> dict[str, Any]:
        return catalog_summary(services.catalog)

    @router.post("/profile", status_code=201)
    async def create_profile(body: InitializeBody, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await collection.initialize(owner, key, body.starter_species_id)

    @router.get("/profile")
    async def get_profile(owner: str = Depends(requester)):
        return await collection.profile(owner)

    @router.get("/species/{species_id}/personalities")
    async def list_personalities(species_id: str, limit: int | None = Query(default=None), cursor: int = Query(default=0),
                                 owner: str = Depends(requester)):
        return await collection.personalities(owner, species_id, limit, cursor)

    @router.get("/species/{species_id}/presets/{slot}")
    async def get_preset(species_id: str, slot: int, owner: str = Depends(requester)):
        return await collection.get_preset(owner, species_id, slot)

    @router.put("/species/{species_id}/presets/{slot}")
    async def put_preset(species_id: str, slot: int, body: PresetBody, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await collection.put_preset(owner, key, species_id, slot, body.instance_ids)

    @router.post("/encounters", status_code=201)
    async def roll_encounter(owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await encounters.roll(owner, key)

    @router.get("/encounters/{encounter_id}")
    async def get_encounter(encounter_id: str, owner: str = Depends(requester)):
        return await encounters.get(owner, encounter_id)

    @router.post("/encounters/{encounter_id}/decline")
    async def decline_encounter(encounter_id: str, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await encounters.decline(owner, key, encounter_id)

    @router.post("/battles", status_code=201)
    async def start_battle(body: StartBody, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await coordinator.start(owner, key, encounter_id=body.encounter_id, species_id=body.species_id,
                                       preset_slot=body.preset_slot, mode=body.mode, emblem_limit=body.emblem_limit)

    @router.get("/battles/{battle_id}")
    async def get_battle(battle_id: str, owner: str = Depends(requester)):
        return await coordinator.view(owner, battle_id)

    @router.post("/battles/{battle_id}/actions")
    async def submit_action(battle_id: str, body: ActionRequest, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await coordinator.submit_action(owner, key, battle_id, round=body.round, revision=body.revision,
                                               action=body.action.model_dump(exclude_none=True))

    @router.post("/battles/{battle_id}/emblem")
    async def answer_emblem(battle_id: str, body: EmblemRequest, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await coordinator.answer_emblem(owner, key, battle_id, round=body.round, revision=body.revision, tier=body.tier)

    @router.post("/battles/{battle_id}/advance")
    async def advance_battle(battle_id: str, body: RoundBody, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await coordinator.advance(owner, key, battle_id, round=body.round, revision=body.revision)

    @router.post("/battles/{battle_id}/mode")
    async def set_mode(battle_id: str, body: ModeRequest, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await coordinator.set_mode(owner, key, battle_id, round=body.round, revision=body.revision,
                                          mode=body.mode, emblem_limit=body.emblem_limit)

    @router.post("/battles/{battle_id}/forfeit")
    async def forfeit(battle_id: str, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await coordinator.forfeit(owner, key, battle_id)

    @router.post("/shop/purchases", status_code=201)
    async def purchase(body: PurchaseBody, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        if body.kind == "emblem":
            return await shop.buy_emblems(owner, key, body.tier, body.quantity)
        if body.kind == "copies" and body.species_id:
            return await shop.buy_copies(owner, key, body.species_id, body.tier)
        raise HTTPException(400, 'kind must be "emblem" (with tier, quantity) or "copies" (with species_id, tier)')

    @router.post("/species/{species_id}/sales", status_code=201)
    async def sell(species_id: str, owner: str = Depends(requester), key: str = Depends(idempotency_key)):
        return await shop.sell_copy(owner, key, species_id)

    return router


def install_error_handlers(app: FastAPI) -> None:
    async def spark_error(request: Request, error: SparkError) -> JSONResponse:
        body: dict[str, Any] = {"error": str(error)}
        if isinstance(error, EncounterCooldown):
            body["retry_after"] = error.retry_after
        return JSONResponse(body, status_code=error.status_code)

    async def catalog_error(request: Request, error: CatalogError) -> JSONResponse:
        return JSONResponse({"error": str(error)}, status_code=400)

    app.add_exception_handler(SparkError, spark_error)
    app.add_exception_handler(CatalogError, catalog_error)


def mount_sparks(app: FastAPI, services: SparkServices) -> None:
    install_error_handlers(app)
    app.include_router(build_router(services))
