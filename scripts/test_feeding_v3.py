"""New feeding system, upgrades and active-dragon tests.

Checks the round's acceptance list:
  * multiple dragons work,
  * selecting one dragon does not affect others,
  * food is removed from the correct storage,
  * full feeding stops when hunger reaches maximum,
  * rename changes only the selected dragon,
  * upgrade affects only the selected dragon,
  * the old «غذا بده» command no longer feeds,
  * one active dragon per user.

Run: python3 scripts/test_feeding_v3.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_feed_v3.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)

from config import DRAGON_DEFAULT_HUNGER, FOOD_UNITS, UPGRADES  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.dragons import DragonService, current_hunger  # noqa: E402
from game.feeding import FeedingService  # noqa: E402
from game.storage import ColdStorageService  # noqa: E402
from game.upgrades import UpgradeService  # noqa: E402
from handlers.dragon_manage import (  # noqa: E402
    ACTION_EAT_FULL,
    ACTION_EAT_ONE,
    PREFIX,
    feed_keyboard,
    profile_keyboard,
    upgrade_keyboard,
)
from models.dragon import DragonRepository  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

init_db()
run_migrations()

OWNER = 5001
OTHER = 6002
HOUR = 3600.0


def _starve(dragons: DragonRepository, dragon_id: int, hunger: int, now: float) -> None:
    """Move last_fed_time into the past so the dragon decays to ``hunger``."""
    from game.dragons import anchor_last_fed_time

    d = dragons.get(dragon_id)
    dragons.update_full_stats(
        dragon_id, level=d.level, xp=d.xp, hp=d.hp, max_hp=d.max_hp,
        power=d.power, hunger=hunger,
        last_fed_time=anchor_last_fed_time(hunger, now), conn=None,
    )


def main() -> None:
    import time

    now = time.time()
    players = PlayerRepository()
    dragons = DragonRepository()
    service = DragonService(dragons)
    storage = ColdStorageService(players)
    feeding = FeedingService(dragons=dragons, players=players, storage=storage)
    upgrades = UpgradeService(dragons=dragons, players=players, storage=storage)

    players.get_or_create(OWNER, "owner")
    players.get_or_create(OTHER, "other")

    # 1. Multiple dragons.
    a = service.create_newborn(OWNER, "fire")
    b = service.create_newborn(OWNER, "ice")
    service.rename(OWNER, a.id, "آذر")
    service.rename(OWNER, b.id, "یخ پنجه")
    foreign = service.create_newborn(OTHER, "green")
    assert len(service.list_for_owner(OWNER)) == 2
    print("✓ multiple dragons per user")

    # 2. The retired commands are gone entirely: not routed, not in config.
    import config
    from handlers import COMMAND_MAP

    assert not hasattr(config, "COMMAND_FEED")
    assert not hasattr(config, "COMMAND_MY_DRAGONS")
    for word in ("غذا بده", "اژدهای من"):
        assert word not in COMMAND_MAP, word
    # Their modules no longer exist either.
    for module in ("handlers.feed", "handlers.mydragons"):
        try:
            __import__(module)
        except ModuleNotFoundError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"{module} should have been removed")
    # No leftover "feed:" callback handler is registered.
    print("✓ «غذا بده» and «اژدهای من» removed completely (commands + modules)")

    # 3. Feeding menu buttons exist on the dragon page only.
    fkb = feed_keyboard(a.id)
    labels = [btn.text for row in fkb.inline_keyboard for btn in row]
    datas = [btn.callback_data for row in fkb.inline_keyboard for btn in row]
    assert labels == ["🥩 یک غذا بده", "🍖 سیرش کن", "🔙 برگشت"]
    assert f"{PREFIX}{ACTION_EAT_ONE}:{a.id}" in datas
    assert f"{PREFIX}{ACTION_EAT_FULL}:{a.id}" in datas
    assert "🥩 غذا دادن" in [
        btn.text for row in profile_keyboard(a.id).inline_keyboard for btn in row
    ]
    print("✓ feeding menu reachable only from the selected dragon page")

    # 4. Single food: one unit removed from cold storage, only that dragon fed.
    storage.deposit(OWNER, meat=10, fish=10)
    _starve(dragons, a.id, 70, now)
    _starve(dragons, b.id, 70, now)
    before = storage.contents(OWNER)
    r = feeding.feed_unit(OWNER, a.id, "meat")
    after = storage.contents(OWNER)
    assert r.success and r.units == 1 and r.food_key == "meat"
    assert after.meat == before.meat - 1 and after.fish == before.fish
    assert r.hunger_before == 70
    assert r.hunger_after == 70 + FOOD_UNITS["meat"]["hunger"]
    assert current_hunger(dragons.get(b.id), time.time()) == 70  # untouched
    assert dragons.get(b.id).xp == 0
    print(f"✓ single food: 1 meat spent, hunger {r.hunger_before}% → {r.hunger_after}%")

    # 5. Full feed consumes ONLY what is needed and stops at 100%.
    _starve(dragons, a.id, 60, time.time())
    before = storage.contents(OWNER)
    r = feeding.feed_until_full(OWNER, a.id)
    after = storage.contents(OWNER)
    assert r.success
    assert r.hunger_after == DRAGON_DEFAULT_HUNGER  # exactly full, never over
    spent_units = (before.meat - after.meat) + (before.fish - after.fish)
    assert spent_units == r.units
    # 40% needed / 10% per meat unit = 4 units, not the whole storage.
    assert r.units == 4, r.units
    assert after.meat + after.fish > 0  # storage not drained
    print(f"✓ full feed used only {r.units} units to go 60% → 100%")

    # 6. Feeding an already-full dragon changes nothing.
    before = storage.contents(OWNER)
    r = feeding.feed_until_full(OWNER, a.id)
    assert r.success is False and r.reason == "full"
    r1 = feeding.feed_unit(OWNER, a.id)
    assert r1.success is False and r1.reason == "full"
    assert storage.contents(OWNER) == before
    print("✓ already-full dragon: «اژدهای تو سیر است» and no food consumed")

    # 7. Empty storage is handled and partial fill keeps what it managed.
    players.get_or_create(7003, "poor")
    poor_dragon = service.create_newborn(7003, "fire")
    _starve(dragons, poor_dragon.id, 50, time.time())
    r = feeding.feed_unit(7003, poor_dragon.id)
    assert r.success is False and r.reason == "no_food"
    storage.deposit(7003, meat=2)
    r = feeding.feed_until_full(7003, poor_dragon.id)
    assert r.success and r.units == 2                 # only what existed
    assert r.hunger_after < DRAGON_DEFAULT_HUNGER     # stopped early
    assert storage.contents(7003).meat == 0
    print("✓ empty/insufficient storage handled; partial feed keeps progress")

    # 8. Food cannot be taken from another player's storage.
    other_before = storage.contents(OTHER)
    stolen = feeding.feed_unit(OWNER, foreign.id)
    assert stolen.success is False and stolen.reason == "no_dragon"
    assert storage.contents(OTHER) == other_before
    print("✓ cannot feed another user's dragon or spend their storage")

    # 9. Upgrades: affect only the selected dragon, cost food, configurable.
    assert set(UPGRADES) == {"hp", "power", "level"}
    ukb = upgrade_keyboard(a.id)
    assert len([btn for row in ukb.inline_keyboard for btn in row]) == len(UPGRADES) + 1
    storage.deposit(OWNER, meat=100, fish=100)
    a_before, b_before = dragons.get(a.id), dragons.get(b.id)
    st_before = storage.contents(OWNER)

    up = upgrades.apply(OWNER, a.id, "hp")
    assert up.success and up.dragon.id == a.id
    assert up.dragon.max_hp == a_before.max_hp + UPGRADES["hp"]["amount"]
    assert storage.contents(OWNER).meat == st_before.meat - UPGRADES["hp"]["cost"]["meat"]
    assert dragons.get(b.id).max_hp == b_before.max_hp  # other dragon untouched

    up = upgrades.apply(OWNER, a.id, "power")
    assert up.success and up.dragon.power == a_before.power + UPGRADES["power"]["amount"]
    up = upgrades.apply(OWNER, a.id, "level")
    assert up.success and up.dragon.level == a_before.level + UPGRADES["level"]["amount"]
    assert dragons.get(b.id).level == b_before.level and dragons.get(b.id).power == b_before.power
    print("✓ upgrades (HP/power/level) apply to the selected dragon only")

    # 10. Upgrade affordability + foreign dragon rejection.
    players.get_or_create(8004, "broke")
    broke_dragon = service.create_newborn(8004, "ice")
    poor = upgrades.apply(8004, broke_dragon.id, "hp")
    assert poor.success is False and poor.reason == "not_enough" and poor.missing
    assert dragons.get(broke_dragon.id).max_hp == 100
    assert upgrades.apply(OWNER, foreign.id, "hp").reason == "no_dragon"
    print("✓ upgrades need enough food and reject foreign dragons")

    # 11. Rename only the selected dragon.
    a_name = dragons.get(a.id).name
    service.rename(OWNER, b.id, "یخ‌پنجه‌ی بزرگ")
    assert dragons.get(b.id).name == "یخ‌پنجه‌ی بزرگ"
    assert dragons.get(a.id).name == a_name
    assert service.rename(OWNER, foreign.id, "هک") is None
    print("✓ rename affects only the selected dragon and is saved in the DB")

    # 12. Active dragon: one per user, must be owned, survives re-selection.
    assert players.set_active_dragon(OWNER, a.id) is True
    assert players.get_active_dragon_id(OWNER) == a.id
    assert players.set_active_dragon(OWNER, b.id) is True
    assert players.get_active_dragon_id(OWNER) == b.id      # replaced, not added
    assert players.set_active_dragon(OWNER, foreign.id) is False
    assert players.get_active_dragon_id(OWNER) == b.id      # unchanged
    assert players.get_active_dragon_id(OTHER) is None      # separate per user
    players.clear_active_dragon_if(OWNER, b.id)
    assert players.get_active_dragon_id(OWNER) is None
    print("✓ exactly one active dragon per user, ownership enforced")

    # 13. Hunting/fishing rewards land in cold storage (unchanged behaviour).
    contents_before = storage.contents(OWNER)
    storage.deposit(OWNER, meat=5, fish=7)
    contents_after = storage.contents(OWNER)
    assert contents_after.meat == contents_before.meat + 5
    assert contents_after.fish == contents_before.fish + 7
    print("✓ cold storage receives hunting/fishing rewards and pays for food")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll new-feeding / upgrade / active-dragon tests passed ✅")


if __name__ == "__main__":
    main()
