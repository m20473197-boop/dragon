"""Dragon egg rarity & origin tests (Version 8).

Checks the round's requirements:
  * every configured egg type has an element and a rarity table,
  * the new egg types exist with the exact chances from the spec,
  * 🌌 تخم اژدهای نخستین never spawns in the wild,
  * elemental eggs always produce their element; کهن rolls a random one,
  * rarity multipliers scale starting HP/power exactly as specified,
  * rarity is persisted and survives a re-read,
  * eggs no longer create identical dragons,
  * existing dragons/rows default to ⚪ معمولی with unchanged stats,
  * the hatch message and dragon screens show element + rarity,
  * eggs, food, cold storage, market, arena, treasury and currency still work.

Run: python3 scripts/test_rarity.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_rarity_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")

import config  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.dragons import DragonService  # noqa: E402
from game.eggs import EggService  # noqa: E402
from game.rarity import (  # noqa: E402
    egg_is_special,
    element_label,
    normalise_rarity,
    rarity_display,
    rarity_label,
    rarity_multiplier,
    rarity_order,
    rarity_table,
    roll_element,
    roll_rarity,
    scaled_stats,
)
from game.storage import ColdStorageService  # noqa: E402
from game.treasury import TreasuryService  # noqa: E402
from models.dragon import DragonRepository  # noqa: E402
from models.egg import EggRepository  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

init_db()
run_migrations()

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, detail=None) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  ❌ {label}" + (f"  [{detail!r}]" if detail is not None else ""))


def main() -> None:
    players = PlayerRepository()
    dragons = DragonRepository()
    eggs = EggRepository()
    service = DragonService(dragons=dragons)
    egg_service = EggService(
        eggs=eggs, dragons=dragons, players=players, dragon_service=service
    )

    print("\n1. Rarity ladder")
    expected = ["normal", "rare", "epic", "legendary", "mythical"]
    check("five rarities exist", list(config.RARITIES) == expected, list(config.RARITIES))
    for key, emoji, name in (
        ("normal", "⚪", "معمولی"), ("rare", "🟢", "کمیاب"), ("epic", "🔵", "حماسی"),
        ("legendary", "🟣", "افسانه‌ای"), ("mythical", "🟡", "اسطوره‌ای"),
    ):
        e, n = rarity_display(key)
        check(f"{key} renders as {emoji} {name}", (e, n) == (emoji, name), (e, n))
    check("order is ascending",
          [rarity_order(r) for r in expected] == [0, 1, 2, 3, 4])

    print("2. Rarity multipliers match the spec")
    for key, mult in (("normal", 1.00), ("rare", 1.10), ("epic", 1.25),
                      ("legendary", 1.50), ("mythical", 2.00)):
        check(f"{key} = x{mult}", rarity_multiplier(key) == mult, rarity_multiplier(key))
    base_hp, base_pw = config.DRAGON_DEFAULT_MAX_HP, config.DRAGON_DEFAULT_POWER
    check("normal keeps base stats", scaled_stats("normal") == (base_hp, base_pw))
    check("rare is +10%", scaled_stats("rare") == (110, 22), scaled_stats("rare"))
    check("epic is +25%", scaled_stats("epic") == (125, 25), scaled_stats("epic"))
    check("legendary is +50%", scaled_stats("legendary") == (150, 30))
    check("mythical is +100%", scaled_stats("mythical") == (200, 40))
    check("stats increase monotonically with rarity", all(
        scaled_stats(a)[0] < scaled_stats(b)[0]
        for a, b in zip(expected, expected[1:])))

    print("3. Unknown / missing rarity degrades safely")
    check("unknown key -> normal", normalise_rarity("bogus") == "normal")
    check("None -> normal", normalise_rarity(None) == "normal")
    check("empty -> normal", normalise_rarity("") == "normal")
    check("label of a bad key still renders", rarity_label("bogus") == "⚪ معمولی")

    print("4. Egg types")
    for key in ("ancient", "eternal_flame", "ice_crystal", "sky_storm",
                "ancient_shadow", "primordial"):
        check(f"«{key}» exists", key in config.EGG_TYPES)
    for key, name, emoji in (
        ("ancient", "تخم کهن", "🥚"),
        ("eternal_flame", "تخم شعله جاودان", "🔥"),
        ("ice_crystal", "تخم کریستال یخی", "❄️"),
        ("sky_storm", "تخم طوفان آسمانی", "⚡"),
        ("ancient_shadow", "تخم سایه باستانی", "🌑"),
        ("primordial", "تخم اژدهای نخستین", "🌌"),
    ):
        spec = config.EGG_TYPES[key]
        check(f"{key} is «{emoji} {name}»",
              spec["name"] == name and spec["emoji"] == emoji,
              (spec["name"], spec["emoji"]))
    # Legacy keys must survive so eggs already in the DB still hatch.
    for legacy in ("common", "rare", "legendary"):
        check(f"legacy egg «{legacy}» still exists", legacy in config.EGG_TYPES)

    print("5. Rarity tables match the spec exactly")
    check("تخم کهن = 75/20/5",
          rarity_table("ancient") == {"normal": 75, "rare": 20, "epic": 5},
          rarity_table("ancient"))
    check("تخم شعله جاودان = 60/25/12/3",
          rarity_table("eternal_flame") ==
          {"normal": 60, "rare": 25, "epic": 12, "legendary": 3},
          rarity_table("eternal_flame"))
    for key, spec in config.EGG_TYPES.items():
        check(f"{key} chances sum to 100", sum(spec["rarity"].values()) == 100,
              sum(spec["rarity"].values()))
        check(f"{key} uses only known rarities",
              all(r in config.RARITIES for r in spec["rarity"]))
    check("🌑 سایه باستانی has better odds than 🥚 کهن",
          rarity_table("ancient_shadow").get("legendary", 0) >
          rarity_table("ancient").get("legendary", 0))
    check("🌌 نخستین can never be ⚪ normal",
          "normal" not in rarity_table("primordial"), rarity_table("primordial"))

    print("6. Elements")
    for key, element in (("eternal_flame", "fire"), ("ice_crystal", "ice"),
                         ("sky_storm", "lightning"),
                         ("ancient_shadow", "shadow"),
                         ("primordial", "primordial")):
        rolls = {roll_element(key) for _ in range(300)}
        check(f"{key} always yields «{element}»", rolls == {element}, rolls)
    ancient_rolls = {roll_element("ancient") for _ in range(600)}
    check("تخم کهن yields a RANDOM element", len(ancient_rolls) > 1, ancient_rolls)
    check("تخم کهن only yields known elements",
          ancient_rolls <= set(config.DRAGON_TYPES), ancient_rolls)
    check("lightning element exists", "lightning" in config.DRAGON_TYPES)
    check("element labels render", element_label("fire") == "🔥 آتش",
          element_label("fire"))
    check("every dragon type has an element name",
          all("element" in v for v in config.DRAGON_TYPES.values()))

    print("7. Special eggs never spawn in the wild")
    check("primordial is special", egg_is_special("primordial"))
    check("common is not special", not egg_is_special("common"))
    check("SPECIAL_EGG_TYPES lists primordial",
          "primordial" in config.SPECIAL_EGG_TYPES)
    wild = Counter(EggService.random_egg_type() for _ in range(20000))
    check("primordial never spawns wild", "primordial" not in wild, dict(wild))
    check("wild spawns cover the normal egg types", len(wild) >= 5, dict(wild))
    for key, spec in config.EGG_TYPES.items():
        if spec["weight"] > 0:
            check(f"{key} can spawn wild", key in wild, dict(wild))

    print("8. Rarity distribution is statistically correct")
    N = 30000
    for key in ("ancient", "eternal_flame", "ancient_shadow"):
        counts = Counter(roll_rarity(key) for _ in range(N))
        for rarity, pct in config.EGG_TYPES[key]["rarity"].items():
            observed = counts[rarity] / N * 100
            check(f"{key}/{rarity} ≈ {pct}% (got {observed:.1f}%)",
                  abs(observed - pct) < 2.0, observed)

    print("9. Newborn dragons carry rarity and scaled stats")
    players.get_or_create(5001, "Owner")
    for rarity in expected:
        d = service.create_newborn(5001, "fire", rarity=rarity)
        hp, pw = scaled_stats(rarity)
        check(f"{rarity} newborn has scaled stats",
              (d.hp, d.max_hp, d.power) == (hp, hp, pw),
              (d.hp, d.max_hp, d.power))
        check(f"{rarity} newborn starts at full HP", d.hp == d.max_hp)
        check(f"{rarity} is persisted", dragons.get(d.id).rarity == rarity,
              dragons.get(d.id).rarity)
        check(f"{rarity} newborn is level 1", d.level == 1 and d.xp == 0)
    plain = service.create_newborn(5001, "ice")
    check("omitting rarity yields ⚪ normal", plain.rarity == "normal")
    check("a normal newborn has the historical stats",
          (plain.hp, plain.max_hp, plain.power) == (100, 100, 20),
          (plain.hp, plain.max_hp, plain.power))

    print("10. Eggs no longer create identical dragons")
    egg_service_local = egg_service
    combos = set()
    rarities = set()
    for _ in range(400):
        et = "legendary"
        combos.add((roll_element(et), roll_rarity(et)))
        rarities.add(roll_rarity(et))
    check("a single egg type produces varied dragons", len(combos) > 3, combos)
    check("a single egg type produces varied rarities", len(rarities) > 1, rarities)

    print("11. A real hatch stores element + rarity")
    players.get_or_create(6001, "Hatcher")
    import time as _t
    made = []
    for i in range(40):
        egg = eggs.create(egg_type="ancient_shadow", chat_id=-900,
                          spawn_time=_t.time() - 100,
                          hatch_time=_t.time() - 5, owner_id=6001,
                          status="incubating")
        made.append(egg)
    events = egg_service_local.process_hatchings()
    check("all due eggs hatched", len(events) == 40, len(events))
    born = [e.dragon for e in events]
    check("every dragon has a valid rarity",
          all(d.rarity in config.RARITIES for d in born))
    check("shadow eggs only produce shadow dragons",
          {d.dragon_type for d in born} == {"shadow"},
          {d.dragon_type for d in born})
    check("hatched rarity is persisted",
          all(dragons.get(d.id).rarity == d.rarity for d in born))
    check("stats always match the stored rarity",
          all((d.max_hp, d.power) == scaled_stats(d.rarity) for d in born),
          [(d.rarity, d.max_hp, d.power) for d in born[:3]])
    check("hatched dragons are not all identical",
          len({(d.max_hp, d.power) for d in born}) > 1,
          {(d.max_hp, d.power) for d in born})

    print("12. Existing dragons default to ⚪ معمولی")
    legacy = dragons.create(5001, "green", None, name="قدیمی")
    check("a dragon created without rarity is normal", legacy.rarity == "normal")
    check("its stats are the historical defaults",
          (legacy.max_hp, legacy.power) == (100, 20),
          (legacy.max_hp, legacy.power))
    # The column is NOT NULL, but a blank or unknown value must still degrade
    # to ⚪ معمولی rather than crash a screen.
    with sqlite3.connect(_tmp_db) as raw:
        raw.execute("UPDATE dragons SET rarity = '' WHERE id = ?", (legacy.id,))
    reread = dragons.get(legacy.id)
    check("a blank rarity row reads back as normal", reread.rarity == "normal",
          reread.rarity)
    check("a blank rarity row keeps its stats",
          (reread.max_hp, reread.power) == (100, 20))
    with sqlite3.connect(_tmp_db) as raw:
        raw.execute("UPDATE dragons SET rarity = 'wat' WHERE id = ?", (legacy.id,))
    check("an unknown rarity renders as ⚪ معمولی",
          rarity_label(dragons.get(legacy.id).rarity) == "⚪ معمولی")

    print("13. UI shows element and rarity")
    from handlers.dragon_manage import profile_text, selection_keyboard
    epic = service.create_newborn(5001, "fire", rarity="epic")
    dragons.set_name(epic.id, 5001, "آذر")
    epic = dragons.get(epic.id)
    card = profile_text(epic, is_active=True)
    check("profile shows the element", "🔮 عنصر: 🔥 آتش" in card, card)
    check("profile shows the rarity", "✨ کمیابی: 🔵 حماسی" in card, card)
    check("profile still shows level/HP/power",
          "⭐ Lv." in card and "❤️ HP:" in card and "قدرت" in card, card)
    kb = selection_keyboard([epic], active_id=epic.id)
    check("the list button carries the rarity dot",
          "🔵" in kb.inline_keyboard[0][0].text, kb.inline_keyboard[0][0].text)

    from handlers.arena import my_dragon_text
    stats = {"dragon": epic, "points": 0, "wins": 0, "losses": 0,
             "league": config.ARENA_LEAGUES[0], "next_league": None,
             "rank": None, "used": 0, "limit": 10}
    atext = my_dragon_text(stats)
    check("arena profile shows element + rarity",
          "🔥 آتش" in atext and "🔵 حماسی" in atext, atext)

    print("14. Other systems still work")
    storage = ColdStorageService(players)
    storage.deposit(5001, meat=30, fish=20)
    c = storage.contents(5001)
    check("cold storage works", (c.meat, c.fish) == (30, 20), (c.meat, c.fish))
    check("food can be spent", storage.consume(5001, "meat", 5) is True)

    players.add_resources(5001, obsidian=5000, aether=4)
    from game.market import MarketService
    check("market works", MarketService(players=players).balance(5001) == 5000)
    from game.tools import ToolService
    check("tools work", ToolService(players=players).level(5001, "rod") >= 1)

    tre = TreasuryService(players=players, eggs=eggs, storage=storage)
    contents = tre.contents(5001)
    check("treasury works", contents.obsidian == 5000 and contents.aether == 4)
    check("treasury lists every egg type",
          len(contents.eggs) == len(config.EGG_TYPES), len(contents.eggs))
    check("treasury egg names are non-empty",
          all(s.name for s in contents.eggs))

    from game.arena import ArenaService, rating
    arena = ArenaService(players=players, dragons=dragons, dragon_service=service)
    check("arena still reads dragons", rating(epic) > 0)
    check("arena stats render", arena.stats(5001)["limit"] == 10)

    from game.upgrades import UpgradeService
    up = UpgradeService(dragons=dragons, players=players)
    before = dragons.get(epic.id).power
    res = up.apply(5001, epic.id, "power")
    check("upgrades still work", res.success, getattr(res, "reason", None))
    check("upgrade raised power from the rarity-scaled base",
          dragons.get(epic.id).power > before)
    check("upgrading does not change rarity",
          dragons.get(epic.id).rarity == "epic")

    from game.feeding import FeedingService
    feeding = FeedingService(dragons=dragons, players=players, storage=storage)
    check("feeding service still constructs", feeding is not None)

    print("15. Migration from a V7 database")
    _migration_test()

    print()
    total = PASSED + FAILED
    if FAILED:
        print(f"❌ {FAILED} of {total} checks failed")
        sys.exit(1)
    print(f"All rarity tests passed ✅  ({PASSED}/{total} checks)")


def _migration_test() -> None:
    """A V7 database (dragons without a rarity column) upgrades in place."""
    import json
    import subprocess

    old = Path(tempfile.mkdtemp()) / "v7.db"
    conn = sqlite3.connect(old)
    conn.executescript(
        """
        CREATE TABLE players (
            user_id INTEGER PRIMARY KEY, username TEXT,
            meat INTEGER NOT NULL DEFAULT 0, fish INTEGER NOT NULL DEFAULT 0,
            eggs INTEGER NOT NULL DEFAULT 0, dragons INTEGER NOT NULL DEFAULT 0,
            last_hunt_time REAL, last_fishing_time REAL,
            hunt_count INTEGER NOT NULL DEFAULT 0,
            fishing_count INTEGER NOT NULL DEFAULT 0,
            active_dragon_id INTEGER,
            obsidian INTEGER NOT NULL DEFAULT 0, aether INTEGER NOT NULL DEFAULT 0,
            rod_level INTEGER NOT NULL DEFAULT 1,
            weapon_level INTEGER NOT NULL DEFAULT 1,
            arena_points INTEGER NOT NULL DEFAULT 0,
            arena_wins INTEGER NOT NULL DEFAULT 0,
            arena_losses INTEGER NOT NULL DEFAULT 0,
            arena_battles_today INTEGER NOT NULL DEFAULT 0,
            arena_last_day TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE dragons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL,
            name TEXT NOT NULL, dragon_type TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1, xp INTEGER NOT NULL DEFAULT 0,
            hp INTEGER NOT NULL DEFAULT 100, max_hp INTEGER NOT NULL DEFAULT 100,
            power INTEGER NOT NULL DEFAULT 20, hunger INTEGER NOT NULL DEFAULT 100,
            last_fed_time REAL, is_test INTEGER NOT NULL DEFAULT 0,
            from_egg_id INTEGER, born_at TEXT);
        CREATE TABLE eggs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER,
            egg_type TEXT NOT NULL, status TEXT NOT NULL, owner_id INTEGER,
            message_id INTEGER, spawn_time REAL, claim_time REAL,
            hatch_time REAL, is_test INTEGER NOT NULL DEFAULT 0,
            delete_after REAL);
        INSERT INTO players (user_id, username, meat, fish, obsidian, aether,
                             rod_level, weapon_level, arena_points)
        VALUES (8888, 'OldTimer', 200, 150, 9000, 20, 5, 7, 300);
        INSERT INTO dragons (owner_id, name, dragon_type, level, xp, hp, max_hp,
                             power, hunger, born_at)
        VALUES (8888, 'اژدهای قدیمی', 'fire', 12, 40, 260, 320, 145, 80,
                '2025-01-01 00:00:00');
        INSERT INTO eggs (chat_id, egg_type, status, owner_id, hatch_time)
        VALUES (-100, 'common', 'incubating', 8888, 99999999999);
        """
    )
    conn.commit()
    conn.close()

    script = """
import json, sqlite3, sys
sys.path.insert(0, %r)
from database.init_db import init_db
from database.migrate import run_migrations
from models.dragon import DragonRepository
from models.player import PlayerRepository
from models.egg import EggRepository
init_db(); run_migrations()
d = DragonRepository().list_by_owner(8888)[0]
p = PlayerRepository().get(8888)
e = EggRepository().list_by_owner(8888)
print(json.dumps({
    "rarity": d.rarity, "name": d.name, "level": d.level, "xp": d.xp,
    "hp": d.hp, "max_hp": d.max_hp, "power": d.power, "hunger": d.hunger,
    "type": d.dragon_type,
    "meat": p.meat, "fish": p.fish, "obsidian": p.obsidian, "aether": p.aether,
    "rod": p.rod_level, "weapon": p.weapon_level, "points": p.arena_points,
    "eggs": len(e),
}))
""" % (str(Path(__file__).resolve().parent.parent),)

    env = dict(os.environ, DRAGON_DB_PATH=str(old), DRAGON_BOT_TOKEN="t:t")
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env
    )
    if proc.returncode != 0:
        check("V7 migration ran", False, proc.stderr[-500:])
        return
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    check("existing dragon survived", out["name"] == "اژدهای قدیمی", out["name"])
    check("existing dragon defaults to ⚪ normal", out["rarity"] == "normal",
          out["rarity"])
    check("existing dragon keeps its level", out["level"] == 12, out["level"])
    check("existing dragon keeps its XP", out["xp"] == 40)
    check("existing dragon keeps its HP", (out["hp"], out["max_hp"]) == (260, 320),
          (out["hp"], out["max_hp"]))
    check("existing dragon keeps its power", out["power"] == 145, out["power"])
    check("existing dragon keeps its hunger", out["hunger"] == 80)
    check("existing dragon keeps its element", out["type"] == "fire")
    check("player food kept", (out["meat"], out["fish"]) == (200, 150))
    check("player currency kept", (out["obsidian"], out["aether"]) == (9000, 20))
    check("player tools kept", (out["rod"], out["weapon"]) == (5, 7))
    check("arena points kept", out["points"] == 300)
    check("existing incubating egg still there", out["eggs"] == 1, out["eggs"])


if __name__ == "__main__":
    main()
