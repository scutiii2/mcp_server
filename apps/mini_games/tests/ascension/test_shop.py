import pytest

from src.ascension.catalog import CatalogError
from src.ascension.errors import InsufficientFunds, InvalidRequest, NothingToSell, WrongPhase
from src.ascension.records import AscendedRecord
from tests.ascension.env import CATALOG, Env, run
from tests.ascension.helpers import battle_record


def make(tmp_path):
    return Env(tmp_path / "s.sqlite3")


async def balance(env, owner="ann"):
    async with env.repo.transaction() as tx:
        return (await tx.get_player(owner)).insignia, await tx.emblem_counts(owner)


def test_emblem_prices_are_a_fifth_of_their_strength(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=1000)
        bought = await env.shop.buy_emblems("ann", "e1", "rare", 3)
        after = await balance(env)
        await env.close()
        return bought, after

    bought, (insignia, emblems) = run(scenario())
    assert bought["price"] == 120 and insignia == 880 and emblems == {"common": 5, "rare": 3}


def test_forbidden_emblems_are_the_most_expensive(tmp_path):
    prices = {t.id: t.emblem_price for t in CATALOG.tiers}
    assert prices == {"common": 20, "rare": 40, "unique": 80, "royal": 160, "legendary": 320, "forbidden": 640}


def test_not_enough_insignia_changes_nothing(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=50)
        with pytest.raises(InsufficientFunds):
            await env.shop.buy_emblems("ann", "e1", "rare", 2)
        result = await balance(env)
        await env.close()
        return result

    assert run(scenario()) == (50, {"common": 5})


@pytest.mark.parametrize("quantity", [0, -1, 100, True, "3"])
def test_bad_quantities_are_rejected(tmp_path, quantity):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        with pytest.raises(InvalidRequest):
            await env.shop.buy_emblems("ann", "e1", "common", quantity)
        await env.close()

    run(scenario())


def test_unknown_tier_is_a_catalog_error(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        with pytest.raises(CatalogError):
            await env.shop.buy_emblems("ann", "e1", "gold", 1)
        await env.close()

    run(scenario())


def test_buying_a_new_ascended_starts_it_at_level_one(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=1000)
        bought = await env.shop.buy_copies("ann", "c1", "sentinel", "common")
        profile = await env.collection.profile("ann")
        await env.close()
        return bought, profile

    bought, profile = run(scenario())
    assert bought["price"] == 2 * 1 * 140 and bought["copies_granted"] == 1
    sentinel = next(s for s in profile["ascendeds"] if s["ascended_id"] == "sentinel")
    assert (sentinel["level"], sentinel["copies"]) == (1, 1) and profile["insignia"] == 1000 - 280


def test_buying_keeps_an_owned_ascended_level_and_prices_at_the_resulting_tier(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=5000, guardian=AscendedRecord("ann", "guardian", 9, 11, 40))
        bought = await env.shop.buy_copies("ann", "c1", "guardian", "rare")  # 9 + 2 = 11 copies -> Rare
        profile = await env.collection.profile("ann")
        await env.close()
        return bought, profile

    bought, profile = run(scenario())
    assert bought["resulting_tier_id"] == "rare" and bought["copies_granted"] == 2
    assert bought["price"] == 2 * 2 * CATALOG.sale_value("guardian", "rare", 11)  # 2 x copies x resale at Rare, level 11
    guardian = profile["ascendeds"][0]
    assert (guardian["level"], guardian["xp"], guardian["copies"]) == (11, 40, 11)


def test_the_forbidden_ascended_and_tier_cannot_be_bought(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=10**6)
        with pytest.raises(InvalidRequest, match="captured"):
            await env.shop.buy_copies("ann", "c1", "forbidden", "common")
        with pytest.raises(InvalidRequest, match="regular tiers"):
            await env.shop.buy_copies("ann", "c2", "sentinel", "forbidden")
        await env.close()

    run(scenario())


def test_selling_pays_the_value_before_the_copy_goes_and_can_downgrade(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(guardian=AscendedRecord("ann", "guardian", 10, 11, 0))  # Rare at 10 copies
        sale = await env.shop.sell_copy("ann", "s1", "guardian")
        insignia, _ = await balance(env)
        await env.close()
        return sale, insignia

    sale, insignia = run(scenario())
    value = CATALOG.sale_value("guardian", "rare", 11)
    assert sale["value"] == value == insignia and sale["downgraded"] is True and sale["tier_id"] == "common" and sale["copies"] == 9


def test_selling_never_removes_the_owned_ascended_or_causes_fainting(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        with pytest.raises(NothingToSell):
            await env.shop.sell_copy("ann", "s1", "guardian")  # zero copies
        with pytest.raises(NothingToSell):
            await env.shop.sell_copy("ann", "s2", "sentinel")  # not owned
        await env.give(guardian=AscendedRecord("ann", "guardian", 1, 1, 0))
        await env.shop.sell_copy("ann", "s3", "guardian")
        profile = await env.collection.profile("ann")
        await env.close()
        return profile["ascendeds"][0]

    ascended = run(scenario())
    assert ascended["copies"] == 0 and ascended["fainted"] is False


@pytest.mark.parametrize("ascended_id", [s.id for s in CATALOG.regular_ascendeds()])
@pytest.mark.parametrize("package", ["common", "rare", "unique", "royal", "legendary"])
@pytest.mark.parametrize("start_copies,level", [(0, 1), (8, 7), (39, 30), (99, 12), (249, 30)])
def test_buying_then_reselling_never_makes_a_profit(ascended_id, package, start_copies, level):
    owned = AscendedRecord("ann", ascended_id, start_copies, level, 0)
    price, granted, resulting = _price(owned, package)
    resale = 0
    copies = owned.copies + granted
    for _ in range(granted):
        tier = CATALOG.tier_for_copies(ascended_id, copies)
        resale += CATALOG.sale_value(ascended_id, tier, level)
        copies -= 1
    assert resale < price


def _price(owned, package):
    from src.ascension.shop import ShopService

    return ShopService(None, CATALOG, None).copy_price(owned.ascended_id, owned, package)


def test_a_ascended_that_is_fighting_cannot_be_bought_or_sold_but_others_can(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=5000, guardian=AscendedRecord("ann", "guardian", 3, 1, 0))
        async with env.repo.transaction() as tx:
            await tx.add_battle(battle_record())  # its fighter is the guardian Ascended by default
        with pytest.raises(WrongPhase):
            await env.shop.buy_copies("ann", "c1", "guardian", "common")
        with pytest.raises(WrongPhase):
            await env.shop.sell_copy("ann", "s1", "guardian")
        await env.shop.buy_copies("ann", "c2", "scout", "common")
        await env.shop.buy_emblems("ann", "e1", "common", 1)
        await env.close()

    run(scenario())


def test_a_retried_purchase_is_charged_once(tmp_path):
    async def scenario():
        env = make(tmp_path)
        await env.start_player()
        await env.give(insignia=1000)
        first = await env.shop.buy_emblems("ann", "same", "common", 2)
        second = await env.shop.buy_emblems("ann", "same", "common", 2)
        result = await balance(env)
        await env.close()
        return first, second, result

    first, second, (insignia, emblems) = run(scenario())
    assert first == second and insignia == 960 and emblems == {"common": 7}
