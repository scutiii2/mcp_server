"""/api/ascension: the Ascension game (apps/mini_games), passed through.

ember_api keeps no game data. It checks the session and ascension.play,
validates every body against mini_games' own rules (unknown fields refused,
so a client can never send rewards, stats or an owner), requires an
Idempotency-Key on every change and forwards the call through the
AscensionGateway, which adds the owner (the account id as text) and the
internal token itself. Bad input is a 400 here and never reaches mini_games.

Changes of value (a new profile, a reset, a battle started or forfeited, a purchase,
a sale) are written to the activity log after they succeeded. Round actions
and advance are not: one line per round would flood the log, and mini_games
records every finished battle itself."""

from __future__ import annotations

import re
from collections.abc import Awaitable
from typing import Annotated, Any, Literal, TypeVar

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from src.deps import get_ascension, get_log_writer, require_permission
from src.models import Account
from src.services.ascension_gateway import UNAVAILABLE_MESSAGE, AscensionApi, AscensionRefused, AscensionUnavailable
from src.services.log_service import LogWriter
from src.services.permissions import ASCENSION_PLAY

router = APIRouter(prefix="/api/ascension", tags=["ascension"])
require_play = require_permission(ASCENSION_PLAY)

ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_ID = re.compile(ID_PATTERN)
_SLOT = re.compile(r"^[1-5]$")
_KEY = re.compile(r"[A-Za-z0-9_.:-]+")
KEY_MAX = 200
PAGE_MAX = 100
EMBLEM_MAX = 99
PRESET_MAX = 3

Id = Annotated[str, Field(pattern=ID_PATTERN)]
Mode = Literal["manual", "autonomous"]
M = TypeVar("M", bound=BaseModel)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileIn(_In):
    starter_ascended_id: Id


class PresetIn(_In):
    instance_ids: list[Id] = Field(max_length=PRESET_MAX)


class BattleStartIn(_In):
    encounter_id: Id
    ascended_id: Id
    preset_slot: StrictInt | None = Field(default=None, ge=1, le=5)
    mode: Mode = "manual"
    emblem_limit: Id | None = None


class RoundIn(_In):
    round: StrictInt = Field(ge=0)
    revision: StrictInt = Field(ge=0)


class ActionChoiceIn(_In):
    kind: Literal["attack", "ability", "flee", "catch"]
    ability_id: Id | None = None
    emblem_tier: Id | None = None


class ActionIn(RoundIn):
    action: ActionChoiceIn


class EmblemIn(RoundIn):
    tier: Id


class ModeIn(RoundIn):
    mode: Mode
    emblem_limit: Id | None = None


class PurchaseIn(_In):
    kind: Literal["emblem", "copies"]
    tier: Id
    quantity: StrictInt = Field(default=1, ge=1, le=EMBLEM_MAX)
    ascended_id: Id | None = None

    @model_validator(mode="after")
    def copies_name_a_ascended(self) -> PurchaseIn:
        if self.kind == "copies" and self.ascended_id is None:
            raise ValueError("copies need a ascended_id")
        return self


def _parse(model: type[M], raw: Any) -> M:
    """A body checked here: a bad one is a 400 with a readable reason."""
    try:
        return model.model_validate(raw)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "body"
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{where}: {first['msg']}") from error


def _id(value: str, what: str) -> str:
    if not _ID.fullmatch(value):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{what} is not a valid id")
    return value


def _slot(value: str) -> int:
    if not _SLOT.fullmatch(value):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "preset slot must be from 1 to 5")
    return int(value)


def idempotency_key(key: str | None = Header(default=None, alias="Idempotency-Key")) -> str:
    value = (key or "").strip()
    if not 1 <= len(value) <= KEY_MAX or not _KEY.fullmatch(value):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"An Idempotency-Key header of 1 to {KEY_MAX} characters (letters, digits and _ . : -) is required",
        )
    return value


async def _forward(call: Awaitable[Any]) -> Any:
    try:
        return await call
    except AscensionUnavailable as error:
        # The fixed message, never str(error): that may name an address or a token problem.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, UNAVAILABLE_MESSAGE) from error
    except AscensionRefused as error:
        raise HTTPException(error.status, str(error)) from error


def _field(result: Any, key: str, default: Any = "?") -> Any:
    return result.get(key, default) if isinstance(result, dict) else default


# --- reads ----------------------------------------------------------------------


@router.get("/catalog")
async def catalog(account: Account = Depends(require_play), game: AscensionApi = Depends(get_ascension)) -> Any:
    return await _forward(game.request("GET", "/ascension/catalog", account))


@router.get("/profile")
async def get_profile(account: Account = Depends(require_play), game: AscensionApi = Depends(get_ascension)) -> Any:
    return await _forward(game.request("GET", "/ascension/profile", account))


@router.get("/ascendeds/{ascended_id}/personalities")
async def personalities(
    ascended_id: str,
    limit: int | None = Query(default=None, ge=1, le=PAGE_MAX),
    cursor: int | None = Query(default=None, ge=0, le=2**63 - 1),
    account: Account = Depends(require_play),
    game: AscensionApi = Depends(get_ascension),
) -> Any:
    # Only these two, as validated integers; any other query parameter is dropped.
    params = {name: value for name, value in (("limit", limit), ("cursor", cursor)) if value is not None}
    path = f"/ascension/ascendeds/{_id(ascended_id, 'ascended_id')}/personalities"
    return await _forward(game.request("GET", path, account, params=params or None))


@router.get("/ascendeds/{ascended_id}/presets/{slot}")
async def get_preset(
    ascended_id: str, slot: str, account: Account = Depends(require_play), game: AscensionApi = Depends(get_ascension)
) -> Any:
    path = f"/ascension/ascendeds/{_id(ascended_id, 'ascended_id')}/presets/{_slot(slot)}"
    return await _forward(game.request("GET", path, account))


@router.get("/encounters/{encounter_id}")
async def get_encounter(
    encounter_id: str, account: Account = Depends(require_play), game: AscensionApi = Depends(get_ascension)
) -> Any:
    return await _forward(game.request("GET", f"/ascension/encounters/{_id(encounter_id, 'encounter_id')}", account))


@router.get("/battles/{battle_id}")
async def get_battle(
    battle_id: str, account: Account = Depends(require_play), game: AscensionApi = Depends(get_ascension)
) -> Any:
    return await _forward(game.request("GET", f"/ascension/battles/{_id(battle_id, 'battle_id')}", account))


# --- changes --------------------------------------------------------------------


@router.post("/profile", status_code=status.HTTP_201_CREATED)
async def create_profile(
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    body = _parse(ProfileIn, raw)
    result = await _forward(
        game.request("POST", "/ascension/profile", account, json=body.model_dump(exclude_none=True), idempotency_key=key)
    )
    await logs.action(account, "ascension.profile_create", f"Started Ascension with the starter '{body.starter_ascended_id}'")
    return result


@router.post("/profile/reset")
async def reset_profile(
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    # No body: the gateway sends confirm itself, so the browser cannot skip it.
    result = await _forward(game.reset_profile(account, key))
    await logs.action(account, "ascension.profile_reset", "Reset all Ascension progress")
    return result


@router.put("/ascendeds/{ascended_id}/presets/{slot}")
async def put_preset(
    ascended_id: str,
    slot: str,
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
) -> Any:
    path = f"/ascension/ascendeds/{_id(ascended_id, 'ascended_id')}/presets/{_slot(slot)}"
    body = _parse(PresetIn, raw)
    return await _forward(game.request("PUT", path, account, json=body.model_dump(exclude_none=True), idempotency_key=key))


@router.post("/encounters", status_code=status.HTTP_201_CREATED)
async def roll_encounter(
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
) -> Any:
    return await _forward(game.request("POST", "/ascension/encounters", account, idempotency_key=key))


@router.post("/encounters/{encounter_id}/decline")
async def decline_encounter(
    encounter_id: str,
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
) -> Any:
    path = f"/ascension/encounters/{_id(encounter_id, 'encounter_id')}/decline"
    return await _forward(game.request("POST", path, account, idempotency_key=key))


@router.post("/battles", status_code=status.HTTP_201_CREATED)
async def start_battle(
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    body = _parse(BattleStartIn, raw)
    result = await _forward(
        game.request("POST", "/ascension/battles", account, json=body.model_dump(exclude_none=True), idempotency_key=key)
    )
    wild = _field(result, "wild", {})
    await logs.action(
        account,
        "ascension.battle_start",
        f"Started a battle against {_field(wild, 'name', 'a wild Ascended')} (level {_field(wild, 'level')})",
    )
    return result


async def _round_change(
    battle_id: str, verb: str, model: type[RoundIn], raw: Any, account: Account, key: str, game: AscensionApi
) -> Any:
    path = f"/ascension/battles/{_id(battle_id, 'battle_id')}/{verb}"
    body = _parse(model, raw)
    return await _forward(game.request("POST", path, account, json=body.model_dump(exclude_none=True), idempotency_key=key))


@router.post("/battles/{battle_id}/actions")
async def submit_action(
    battle_id: str,
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
) -> Any:
    return await _round_change(battle_id, "actions", ActionIn, raw, account, key, game)


@router.post("/battles/{battle_id}/emblem")
async def answer_emblem(
    battle_id: str,
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
) -> Any:
    return await _round_change(battle_id, "emblem", EmblemIn, raw, account, key, game)


@router.post("/battles/{battle_id}/advance")
async def advance_battle(
    battle_id: str,
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
) -> Any:
    return await _round_change(battle_id, "advance", RoundIn, raw, account, key, game)


@router.post("/battles/{battle_id}/mode")
async def set_mode(
    battle_id: str,
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
) -> Any:
    return await _round_change(battle_id, "mode", ModeIn, raw, account, key, game)


@router.post("/battles/{battle_id}/forfeit")
async def forfeit(
    battle_id: str,
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    battle = _id(battle_id, "battle_id")
    result = await _forward(game.request("POST", f"/ascension/battles/{battle}/forfeit", account, idempotency_key=key))
    await logs.action(account, "ascension.battle_forfeit", f"Forfeited battle {battle}")
    return result


@router.post("/shop/purchases", status_code=status.HTTP_201_CREATED)
async def purchase(
    raw: Any = Body(default=None),
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    body = _parse(PurchaseIn, raw)
    result = await _forward(
        game.request("POST", "/ascension/shop/purchases", account, json=body.model_dump(exclude_none=True), idempotency_key=key)
    )
    if body.kind == "emblem":
        message = (
            f"Bought {_field(result, 'quantity', body.quantity)} {body.tier} EMBLEMs "
            f"for {_field(result, 'price')} Insignia"
        )
    else:
        message = (
            f"Bought {_field(result, 'copies_granted')} {body.ascended_id} copies ({body.tier}) "
            f"for {_field(result, 'price')} Insignia"
        )
    await logs.action(account, "ascension.shop_buy", message)
    return result


@router.post("/ascendeds/{ascended_id}/sales", status_code=status.HTTP_201_CREATED)
async def sell_copy(
    ascended_id: str,
    account: Account = Depends(require_play),
    key: str = Depends(idempotency_key),
    game: AscensionApi = Depends(get_ascension),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    ascended = _id(ascended_id, "ascended_id")
    result = await _forward(game.request("POST", f"/ascension/ascendeds/{ascended}/sales", account, idempotency_key=key))
    await logs.action(account, "ascension.ascended_sell", f"Sold a {ascended} copy for {_field(result, 'value')} Insignia")
    return result
