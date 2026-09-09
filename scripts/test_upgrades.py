"""Dragon upgrade system tests (obsidian-based).

Checks the round's requirements:
  * upgrades cost 🪨 obsidian and NEVER food,
  * the upgrade menu offers HP / power / level + back,
  * each upgrade affects only the selected dragon,
  * upgrades are refused without enough obsidian (balance never negative),
  * costs are configurable,
  * changes are saved in the database.

Run: python3 scripts/test_upgrades.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_upgrades_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)

from config import (  # noqa: E402
    LEVEL_UP_MAX_HP_BONUS,
    LEVEL_UP_POWER_BONUS,
    UPGRADES,
)
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.dragons import DragonService  # noqa: E402
from game.storage import ColdStorageService  # noqa: E402
from game.upgrades import UpgradeService, level_upgrade_cost  # noqa: E402
from handlers.dragon_manage import (  # noqa: E402
    ACTION_UPGRADE,
    PREFIX,
    profile_keyboard,
    upgrade_keyboard,
    upgrade_menu_text,
)
from models.dragon import DragonRepository  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

init_db()
run_migrations()

OWNER = 4001
OTHER = 4002


def main() -> None:
    players = PlayerRepository()
    dragons = DragonRepository()
    service = DragonService(dragons)
    storage = ColdStorageService(players)
    upgrades = UpgradeService(dragons=dragons, players=players)

    players.get_or_create(OWNER, "owner")
    players.get_or_create(OTHER, "other")

    a = service.create_newborn(OWNER, "fire")
    b = service.create_newborn(OWNER, "ice")
    service.rename(OWNER, a.id, "آذر")
    service.rename(OWNER, b.id, "یخ پنجه")
    foreign = service.create_newborn(OTHER, "green")

    # 1. Costs are obsidian only — no food cost remains anywhere.
    assert set(UPGRADES) == {"hp", "power", "level"}
    for key, spec in UPGRADES.items():
        assert "cost" not in spec, f"{key} still has a food cost"
        assert isinstance(spec["cost_obsidian"], int) and spec["cost_obsidian"] > 0
    assert UPGRADES["hp"]["cost_obsidian"] == 500
    assert UPGRADES["power"]["cost_obsidian"] == 700
    assert UPGRADES["level"]["cost_obsidian"] > 0        # fallback, now progressive
    print("✓ upgrades priced in obsidian only (HP 500 / power 700 / level configurable)")

    # 2. The upgrade button lives on the dragon profile page.
    profile_btns = [b_.text for row in profile_keyboard(a.id).inline_keyboard for b_ in row]
    assert "⬆️ ارتقا" in profile_btns
    upgrade_cb = [
        b_.callback_data for row in profile_keyboard(a.id).inline_keyboard for b_ in row
        if b_.text == "⬆️ ارتقا"
    ][0]
    assert upgrade_cb == f"{PREFIX}{ACTION_UPGRADE}:{a.id}"
    print("✓ «⬆️ ارتقا» exists on the selected dragon's profile page")

    # 3. The upgrade menu shows the three upgrades + back, bound to this dragon.
    kb = upgrade_keyboard(a.id)
    labels = [b_.text for row in kb.inline_keyboard for b_ in row]
    datas = [b_.callback_data for row in kb.inline_keyboard for b_ in row]
    assert len(labels) == 4
    assert "HP" in labels[0] and "❤️" in labels[0]
    assert "قدرت" in labels[1] and "⚔️" in labels[1]
    assert "سطح" in labels[2] and "⭐" in labels[2]
    assert labels[3] == "🔙"
    assert all(f":{a.id}:" in d for d in datas[:3])      # bound to this dragon
    assert str(b.id) not in "".join(datas[:3])
    text = upgrade_menu_text(dragons.get(a.id), 1500)
    assert "⬆️ ارتقا" in text and "🪨" in text and "آذر" in text
    print("✓ upgrade menu: ❤️ / 🔥 / ⭐ / 🔙 with obsidian prices")

    # 4. HP upgrade: costs obsidian, +20 max HP, no food touched.
    players.add_resources(OWNER, obsidian=5000)
    storage.deposit(OWNER, meat=50, fish=50)
    food_before = storage.contents(OWNER)
    obs_before = players.get(OWNER).obsidian
    a_before, b_before = dragons.get(a.id), dragons.get(b.id)

    res = upgrades.apply(OWNER, a.id, "hp")
    assert res.success and res.spent == 500
    assert res.dragon.max_hp == a_before.max_hp + 20
    assert res.dragon.hp == res.dragon.max_hp            # healed to the new max
    assert players.get(OWNER).obsidian == obs_before - 500
    assert res.balance == players.get(OWNER).obsidian
    after_food = storage.contents(OWNER)
    assert (after_food.meat, after_food.fish) == (food_before.meat, food_before.fish)
    print("✓ ❤️ HP upgrade: -🪨۵۰۰, +۲۰ max HP, food untouched")

    # 5. Power upgrade: -700 obsidian, +5 power.
    obs_before = players.get(OWNER).obsidian
    res = upgrades.apply(OWNER, a.id, "power")
    assert res.success and res.spent == 700
    assert res.dragon.power == a_before.power + 5
    assert players.get(OWNER).obsidian == obs_before - 700
    print("✓ 🔥 power upgrade: -🪨۷۰۰, +۵ power")

    # 6. Level upgrade: +1 level with the usual per-level bonuses.
    obs_before = players.get(OWNER).obsidian
    lvl_before = dragons.get(a.id)
    # The level upgrade is priced progressively from the dragon's CURRENT level.
    expected_cost = level_upgrade_cost(lvl_before.level)
    res = upgrades.apply(OWNER, a.id, "level")
    assert res.success and res.spent == expected_cost, (res.spent, expected_cost)
    assert res.dragon.level == lvl_before.level + 1
    assert res.dragon.max_hp == lvl_before.max_hp + LEVEL_UP_MAX_HP_BONUS
    assert res.dragon.power == lvl_before.power + LEVEL_UP_POWER_BONUS
    assert players.get(OWNER).obsidian == obs_before - expected_cost
    print("✓ ⭐ level upgrade: -🪨 configurable, +۱ level")

    # 7. Only the selected dragon changed; the other one is untouched.
    b_now = dragons.get(b.id)
    assert (b_now.level, b_now.max_hp, b_now.power, b_now.hp) == (
        b_before.level, b_before.max_hp, b_before.power, b_before.hp
    )
    print("✓ the other dragon of the same owner is completely unaffected")

    # 8. Changes are persisted (re-read straight from the database).
    persisted = dragons.get(a.id)
    assert persisted.max_hp == a_before.max_hp + 20 + LEVEL_UP_MAX_HP_BONUS
    assert persisted.power == a_before.power + 5 + LEVEL_UP_POWER_BONUS
    assert persisted.level == a_before.level + 1
    print("✓ upgraded stats are saved in the database")

    # 9. Not enough obsidian -> rejected, nothing changes, never negative.
    players.get_or_create(4003, "broke")
    broke_dragon = service.create_newborn(4003, "ice")
    before = dragons.get(broke_dragon.id)
    res = upgrades.apply(4003, broke_dragon.id, "hp")
    assert not res.success and res.reason == "not_enough"
    assert res.missing == 500
    after = dragons.get(broke_dragon.id)
    assert (after.max_hp, after.power, after.level) == (
        before.max_hp, before.power, before.level
    )
    assert players.get(4003).obsidian == 0 >= 0
    # Partially funded is refused too.
    players.add_resources(4003, obsidian=499)
    res = upgrades.apply(4003, broke_dragon.id, "hp")
    assert not res.success and res.missing == 1
    assert players.get(4003).obsidian == 499     # not spent, not negative
    print("✓ insufficient obsidian is refused; balance never goes negative")

    # 10. Foreign dragons and unknown upgrades are rejected.
    obs_before = players.get(OWNER).obsidian
    assert upgrades.apply(OWNER, foreign.id, "hp").reason == "no_dragon"
    assert upgrades.apply(OWNER, a.id, "wings").reason == "unknown"
    assert players.get(OWNER).obsidian == obs_before   # nothing charged
    print("✓ another user's dragon and unknown upgrades are rejected free of charge")

    # 11. Helpers report price/affordability correctly.
    assert upgrades.price("hp") == 500
    assert upgrades.missing_for(4003, "hp") == 1
    assert upgrades.affordable(OWNER, "hp") is True
    assert upgrades.affordable(4003, "hp") is False
    print("✓ price/affordability helpers agree with the configuration")

    # 12. Concurrent taps cannot overspend the same obsidian.
    import threading

    players.get_or_create(4004, "tapper")
    tap_dragon = service.create_newborn(4004, "fire")
    players.add_resources(4004, obsidian=500)      # exactly one HP upgrade
    results = []
    lock = threading.Lock()

    def _tap():
        r = UpgradeService().apply(4004, tap_dragon.id, "hp")
        with lock:
            results.append(r)

    threads = [threading.Thread(target=_tap) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    wins = [r for r in results if r.success]
    assert len(wins) == 1, f"expected one upgrade, got {len(wins)}"
    final_player = players.get(4004)
    final_dragon = dragons.get(tap_dragon.id)
    assert final_player.obsidian == 0
    assert final_dragon.max_hp == 100 + 20         # applied exactly once
    print("✓ 10 simultaneous taps -> exactly one upgrade, no overspend")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll upgrade tests passed ✅")


if __name__ == "__main__":
    main()
