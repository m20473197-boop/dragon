"""Progressive dragon upgrade costs.

The ⭐ level upgrade must get more expensive as the dragon levels up:
the exact table for levels 1..9, the formula from level 10, correct charging,
and refusal (with no side effects) when the player cannot afford it.
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")
os.environ["DRAGON_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "costs.db")

import config  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.upgrades import UpgradeService, level_upgrade_cost  # noqa: E402
from handlers import dragon_manage as dm  # noqa: E402
from models.dragon import DragonRepository  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

RESULTS = []
OWNER = 4242

# The costs required by the design.
EXPECTED = {
    1: 1000,
    2: 2000,
    3: 3500,
    4: 5500,
    5: 8000,
    6: 12000,
    7: 18000,
    8: 27000,
    9: 40000,
}


def check(name, cond, extra=""):
    RESULTS.append(bool(cond))
    print(("✅" if cond else "❌"), name, ("→ " + str(extra)) if not cond else "")


def make_dragon(dragons, level, hp=100):
    d = dragons.create(OWNER, "fire", None, name=f"L{level}", level=level,
                       xp=0, hp=hp, max_hp=hp, power=20, hunger=100,
                       last_fed_time=None)
    return d


def main():
    init_db()
    run_migrations()

    players = PlayerRepository()
    dragons = DragonRepository()
    upgrades = UpgradeService(dragons=dragons, players=players)
    players.get_or_create(OWNER, "tester")

    # ---------- the exact table ----------
    for level, cost in EXPECTED.items():
        check(f"level {level} → {level + 1} costs {cost}",
              level_upgrade_cost(level) == cost, level_upgrade_cost(level))

    # ---------- the formula from level 10 ----------
    for level in (10, 11, 12, 15, 20, 30, 50):
        expected = round(40000 * (level / 10) ** 1.8)
        check(f"level {level} uses the formula ({expected})",
              level_upgrade_cost(level) == expected, level_upgrade_cost(level))

    # ---------- curve properties ----------
    costs = [level_upgrade_cost(l) for l in range(1, 41)]
    check("cost never decreases", all(b >= a for a, b in zip(costs, costs[1:])))
    # The table's 9→10 price and the formula's level-10 price are both 40000,
    # so there is exactly ONE plateau (levels 9 and 10) and it is intentional:
    # it is where the hand-tuned table hands over to the formula.
    plateaus = [l for l in range(1, 41)
                if level_upgrade_cost(l) == level_upgrade_cost(l + 1)]
    check("only one plateau, at the table/formula handover",
          plateaus == [9], plateaus)
    check("cost strictly increases everywhere else",
          all(level_upgrade_cost(l + 1) > level_upgrade_cost(l)
              for l in range(1, 41) if l != 9))
    check("table and formula agree at level 10",
          level_upgrade_cost(10) == 40000 == round(40000 * (10 / 10) ** 1.8))
    check("no downward jump at the boundary",
          level_upgrade_cost(10) >= level_upgrade_cost(9))
    check("level 9 costs 40x level 1", level_upgrade_cost(9) == 40 * level_upgrade_cost(1))
    check("all costs are ints", all(isinstance(c, int) for c in costs))

    # corrupt/edge levels must not be free
    check("level 0 clamps to the level-1 price", level_upgrade_cost(0) == 1000)
    check("negative level clamps to the level-1 price", level_upgrade_cost(-5) == 1000)

    # ---------- service pricing ----------
    check("price('level', 5) is level-aware", upgrades.price("level", 5) == 8000)
    check("price('level', 9) is level-aware", upgrades.price("level", 9) == 40000)
    check("flat hp price is unchanged",
          upgrades.price("hp") == config.UPGRADES["hp"]["cost_obsidian"] == 500)
    check("flat power price is unchanged",
          upgrades.price("power") == config.UPGRADES["power"]["cost_obsidian"] == 700)
    check("hp price ignores the dragon level", upgrades.price("hp", 9) == 500)
    check("unknown upgrade prices at 0", upgrades.price("nope", 5) == 0)

    # ---------- charging the right amount ----------
    d5 = make_dragon(dragons, 5)
    players.add_resources(OWNER, obsidian=100000)
    before = players.get(OWNER).obsidian
    res = upgrades.apply(OWNER, d5.id, "level")
    check("level-5 upgrade succeeds", res.success, res.reason)
    check("level-5 upgrade charges 8000", res.spent == 8000, res.spent)
    check("balance drops by exactly 8000",
          players.get(OWNER).obsidian == before - 8000)
    check("dragon reached level 6", res.dragon.level == 6, res.dragon.level)
    check("result reports the previous level", res.previous_level == 5, res.previous_level)
    check("result reports the next cost (12000)", res.next_cost == 12000, res.next_cost)

    # the SAME dragon now costs more
    before2 = players.get(OWNER).obsidian
    res2 = upgrades.apply(OWNER, d5.id, "level")
    check("the next upgrade costs more", res2.spent == 12000, res2.spent)
    check("cost rose between consecutive upgrades", res2.spent > res.spent)
    check("balance drops by exactly 12000",
          players.get(OWNER).obsidian == before2 - 12000)
    check("dragon reached level 7", res2.dragon.level == 7)

    # a high-level dragon uses the formula
    d12 = make_dragon(dragons, 12)
    before3 = players.get(OWNER).obsidian
    res3 = upgrades.apply(OWNER, d12.id, "level")
    expected12 = round(40000 * (12 / 10) ** 1.8)
    check(f"level-12 upgrade charges the formula price ({expected12})",
          res3.spent == expected12, res3.spent)
    check("balance drops by the formula price",
          players.get(OWNER).obsidian == before3 - expected12)

    # ---------- refusal when too poor ----------
    poor = 777
    players.get_or_create(poor, "poor")
    dp = dragons.create(poor, "ice", None, name="Poor", level=9, xp=0, hp=100,
                        max_hp=100, power=20, hunger=100, last_fed_time=None)
    players.add_resources(poor, obsidian=100)
    res4 = upgrades.apply(poor, dp.id, "level")
    check("poor player is refused", not res4.success and res4.reason == "not_enough",
          res4.reason)
    check("refusal reports the right shortfall",
          res4.missing == 40000 - 100, res4.missing)
    check("no obsidian was taken", players.get(poor).obsidian == 100)
    check("dragon level unchanged after refusal",
          dragons.get(dp.id).level == 9, dragons.get(dp.id).level)

    # affording exactly the price works
    players.add_resources(poor, obsidian=40000 - 100)
    check("balance is exactly the price", players.get(poor).obsidian == 40000)
    res5 = upgrades.apply(poor, dp.id, "level")
    check("exact balance is enough", res5.success, res5.reason)
    check("spends the whole balance", players.get(poor).obsidian == 0)
    check("reached level 10", dragons.get(dp.id).level == 10)

    # and now cannot afford the next one
    res6 = upgrades.apply(poor, dp.id, "level")
    check("cannot afford the next level", not res6.success and res6.reason == "not_enough")
    check("still level 10", dragons.get(dp.id).level == 10)

    # ---------- helpers ----------
    check("affordable() is level-aware",
          upgrades.affordable(OWNER, "level", 1) is True
          and upgrades.affordable(poor, "level", 10) is False)
    check("missing_for() is level-aware",
          upgrades.missing_for(poor, "level", 10) == level_upgrade_cost(10))

    # ---------- UI ----------
    d = dragons.get(d5.id)          # level 7 by now
    text = dm.upgrade_menu_text(d, 99999)
    check("card title is ⬆️ ارتقای اژدها", text.startswith("⬆️ ارتقای اژدها"), text)
    check("card shows the dragon name", f"🐉 {d.name}" in text, text)
    check("card shows the current level", "⭐ Level:" in text, text)
    check("card shows this dragon's level price",
          str_fa(level_upgrade_cost(d.level)) in text, text)

    kb = dm.upgrade_keyboard(d.id, d.level)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    lvl_btn = [l for l in labels if "سطح" in l]
    check("level button shows the progressive price",
          lvl_btn and str_fa(level_upgrade_cost(d.level)) in lvl_btn[0], labels)
    check("hp button still shows the flat price",
          any("HP" in l and str_fa(500) in l for l in labels), labels)

    # a level-1 and a level-9 dragon must render different level prices
    d1 = make_dragon(dragons, 1)
    d9 = make_dragon(dragons, 9)
    t1 = dm.upgrade_menu_text(dragons.get(d1.id), 0)
    t9 = dm.upgrade_menu_text(dragons.get(d9.id), 0)
    check("level-1 card shows 1000", str_fa(1000) in t1, t1)
    check("level-9 card shows 40000", str_fa(40000) in t9, t9)
    check("the two cards differ", t1 != t9)

    # ---------- untouched systems ----------
    check("XP is not changed by an upgrade", res.dragon.xp == 0, res.dragon.xp)
    check("hp/power upgrades still work",
          upgrades.apply(OWNER, d1.id, "hp").success
          and upgrades.apply(OWNER, d1.id, "power").success)
    check("config still exposes the flat prices",
          all("cost_obsidian" in spec for spec in config.UPGRADES.values()))

    print()
    passed = sum(RESULTS)
    print(f"{passed}/{len(RESULTS)} checks passed")
    if passed == len(RESULTS):
        print("All upgrade-cost tests passed ✅")
    return 0 if passed == len(RESULTS) else 1


def str_fa(n):
    from utils.text import to_fa
    return to_fa(n)


if __name__ == "__main__":
    sys.exit(main())
