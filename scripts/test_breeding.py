"""Dragon breeding tests — 🧬 آیین پیوند اژدها (Version 9).

Checks the round's requirements:
  * /breeding and «پیوند» both open the same menu with the specified buttons,
  * both parents must be owned, distinct, free and at least Level 10,
  * cost is paid in ✨ اتر and rises when both parents are rare,
  * a ritual locks the parents for 12 hours,
  * a busy dragon cannot fight in the arena, be fed or be upgraded,
  * outcomes are 70% inherit / 25% hybrid / 5% mutation,
  * hybrids match the specified element pairs,
  * mutations are rarer than the parents and get +30% HP/power,
  * the child is an ordinary dragon using the EXISTING rarity/element systems,
  * concurrency: a double tap cannot start two rituals or double-charge,
  * existing players/dragons stay compatible,
  * dragons, eggs, arena, market, treasury, food, hunting, fishing and
    currency all still work.

Run: python3 scripts/test_breeding.py
"""
from __future__ import annotations

import asyncio
import os
import random
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_breeding_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")

import config  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.arena import REASON_BUSY_BREEDING, ArenaService  # noqa: E402
from game.breeding import (  # noqa: E402
    OUTCOME_HYBRID,
    OUTCOME_INHERIT,
    OUTCOME_MUTATION,
    REASON_ALREADY_BREEDING,
    REASON_BUSY,
    REASON_NOT_ENOUGH_AETHER,
    REASON_NOT_OWNED,
    REASON_SAME_DRAGON,
    REASON_TOO_LOW_LEVEL,
    BreedingService,
    bump_rarity,
    hybrid_for,
    pair_cost,
    plan_child,
    rarity_cost,
    roll_outcome,
)
from game.dragons import DragonService  # noqa: E402
from game.feeding import FeedingService  # noqa: E402
from game.rarity import rarity_order, scaled_stats  # noqa: E402
from game.storage import ColdStorageService  # noqa: E402
from game.treasury import TreasuryService  # noqa: E402
from game.upgrades import UpgradeService  # noqa: E402
from handlers import breeding as bh  # noqa: E402
from models.breeding import BreedingRepository  # noqa: E402
from models.dragon import DragonRepository  # noqa: E402
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


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FakeQuery:
    def __init__(self, user_id, data, chat_id=-800):
        self.from_user = type(
            "U", (), {"id": user_id, "username": f"u{user_id}", "is_bot": False}
        )()
        self.data = data
        self.toasts = []
        self.alerts = []
        self.text = None
        self.markup = None
        self.message = type("M", (), {"chat_id": chat_id, "message_id": 3})()

    async def answer(self, text=None, show_alert=False):
        self.toasts.append(text)
        if show_alert:
            self.alerts.append(text)

    async def edit_message_text(self, text, reply_markup=None, **kw):
        self.text = text
        self.markup = reply_markup


def labels(markup):
    if markup is None:
        return []
    return [b.text for row in markup.inline_keyboard for b in row]


def mk(dragons, players, owner, name, level=12, rarity="normal", dtype="fire"):
    players.get_or_create(owner, f"u{owner}")
    hp, pw = scaled_stats(rarity)
    d = dragons.create(owner, dtype, None, name=name, level=level, xp=0,
                       hp=hp, max_hp=hp, power=pw, rarity=rarity)
    return dragons.get(d.id)


def main() -> None:
    players = PlayerRepository()
    dragons = DragonRepository()
    dragon_service = DragonService(dragons=dragons)
    repo = BreedingRepository()
    service = BreedingService(dragons=dragons, players=players, breedings=repo,
                              dragon_service=dragon_service)
    storage = ColdStorageService(players)

    print("\n1. Cost table matches the spec")
    for rarity, cost in (("normal", 5), ("rare", 10), ("epic", 20),
                         ("legendary", 40), ("mythical", 80)):
        check(f"{rarity} costs ✨{cost}", rarity_cost(rarity) == cost,
              rarity_cost(rarity))
        check(f"a {rarity} pair base price is ✨{cost}",
              pair_cost(rarity, "normal") == cost or rarity == "normal",
              pair_cost(rarity, "normal"))
    check("⚪+⚪ = ✨5", pair_cost("normal", "normal") == 5,
          pair_cost("normal", "normal"))
    check("cost rises when BOTH parents are rare",
          pair_cost("rare", "rare") > pair_cost("rare", "normal"),
          (pair_cost("rare", "rare"), pair_cost("rare", "normal")))
    check("a rarer pair always costs more",
          pair_cost("mythical", "mythical") > pair_cost("legendary", "legendary")
          > pair_cost("epic", "epic") > pair_cost("rare", "rare"))
    check("cost is never zero", all(
        pair_cost(a, b) > 0 for a in config.RARITIES for b in config.RARITIES))

    print("2. Requirements are enforced")
    players.get_or_create(1, "Ali")
    players.add_resources(1, aether=500)
    a = mk(dragons, players, 1, "آذر", level=12)
    b = mk(dragons, players, 1, "رعد", level=12, dtype="ice")
    low = mk(dragons, players, 1, "کوچولو", level=3)
    foreign = mk(dragons, players, 2, "غریبه", level=15)

    check("a valid pair previews ok", service.preview(1, a.id, b.id).ok)
    check("the same dragon twice is refused",
          service.preview(1, a.id, a.id).reason == REASON_SAME_DRAGON)
    check("a low-level parent is refused",
          service.preview(1, a.id, low.id).reason == REASON_TOO_LOW_LEVEL)
    check("another player's dragon is refused",
          service.preview(1, a.id, foreign.id).reason == REASON_NOT_OWNED)
    check("minimum level is 10", config.BREEDING_MIN_LEVEL == 10)
    players.get_or_create(3, "Solo")
    only = mk(dragons, players, 3, "تک", level=12)
    check("a player with one dragon is refused",
          service.preview(3, only.id, only.id).ok is False)

    print("3. Starting a ritual charges aether and locks the parents")
    before = players.get(1).aether
    expected_cost = pair_cost(a.rarity, b.rarity)
    start = service.start(1, a.id, b.id, chat_id=-800)
    check("ritual started", start.ok, start.reason)
    check("cost was quoted correctly", start.cost == expected_cost, start.cost)
    check("aether was spent", players.get(1).aether == before - expected_cost,
          players.get(1).aether)
    check("parent 1 is busy", dragons.get(a.id).breeding_status == "breeding")
    check("parent 2 is busy", dragons.get(b.id).breeding_status == "breeding")
    check("finish time is 12 hours out",
          abs((start.breeding.finish_time - start.breeding.start_time)
              - config.BREEDING_DURATION_SECONDS) < 2)
    check("12 hours is the configured duration",
          config.BREEDING_DURATION_SECONDS == 12 * 3600)
    check("the ritual is retrievable", service.active(1) is not None)
    check("busy dragons drop out of the selectable list",
          a.id not in {d.id for d in service.selectable(1)})

    print("4. A busy dragon cannot be used elsewhere")
    # Arena
    players.set_active_dragon(1, a.id)
    arena = ArenaService(players=players, dragons=dragons,
                         dragon_service=dragon_service)
    res = arena.fight(1, rng=random.Random(1))
    check("a busy dragon cannot enter the arena",
          not res.ok and res.reason == REASON_BUSY_BREEDING, res.reason)
    # Feeding
    storage.deposit(1, meat=50, fish=50)
    feeding = FeedingService(dragons=dragons, players=players, storage=storage)
    fed = feeding.feed_unit(1, a.id, "meat")
    check("a busy dragon cannot be fed",
          not fed.success and fed.reason == "busy", fed.reason)
    check("feeding a busy dragon consumes no food",
          storage.contents(1).meat == 50, storage.contents(1).meat)
    # Upgrades
    players.add_resources(1, obsidian=100000)
    up = UpgradeService(dragons=dragons, players=players)
    power_before = dragons.get(a.id).power
    ures = up.apply(1, a.id, "power")
    check("a busy dragon cannot be upgraded",
          not ures.success and ures.reason == "busy", ures.reason)
    check("a refused upgrade changes nothing",
          dragons.get(a.id).power == power_before)
    # Second ritual
    c = mk(dragons, players, 1, "سوم", level=12)
    d2 = mk(dragons, players, 1, "چهارم", level=12)
    second = service.start(1, c.id, d2.id)
    check("a second concurrent ritual is refused",
          not second.ok and second.reason == REASON_ALREADY_BREEDING,
          second.reason)
    check("a busy parent cannot be re-selected",
          service.preview(1, a.id, c.id).reason in
          (REASON_BUSY, REASON_ALREADY_BREEDING))

    print("5. A busy dragon is not offered as an arena opponent")
    players.get_or_create(9, "Rival")
    rival = mk(dragons, players, 9, "حریف", level=12)
    players.set_active_dragon(9, rival.id)
    opponent = arena.find_opponent(9)
    if opponent is not None:
        check("a busy dragon is never matched",
              opponent[1].breeding_status != "breeding",
              opponent[1].breeding_status)
    else:
        check("no opponent found (busy dragons excluded)", True)

    print("6. Completing the ritual produces a child")
    # Fast-forward by rewriting the finish time.
    with sqlite3.connect(_tmp_db) as raw:
        raw.execute("UPDATE breedings SET finish_time = ? WHERE breeding_id = ?",
                    (time.time() - 1, start.breeding.breeding_id))
    dragons_before = players.get(1).dragons
    results = service.collect_due(rng=random.Random(5))
    check("one ritual completed", len(results) == 1, len(results))
    result = results[0]
    child = result.child
    check("a child dragon was created", child is not None and child.id)
    check("the child belongs to the owner", child.owner_id == 1)
    check("the child is level 1", child.level == 1 and child.xp == 0)
    check("the child records both parents",
          {child.parent_dragon_1, child.parent_dragon_2} == {a.id, b.id},
          (child.parent_dragon_1, child.parent_dragon_2))
    check("the child uses a real element", child.dragon_type in config.DRAGON_TYPES)
    check("the child uses a real rarity", child.rarity in config.RARITIES)
    check("the child starts at full HP", child.hp == child.max_hp)
    check("the dragon counter went up", players.get(1).dragons == dragons_before + 1)
    check("parent 1 is free again", dragons.get(a.id).breeding_status == "idle")
    check("parent 2 is free again", dragons.get(b.id).breeding_status == "idle")
    check("the ritual is no longer active", service.active(1) is None)
    check("the ritual recorded the child",
          repo.get(start.breeding.breeding_id).child_id == child.id)
    check("collecting twice does not duplicate the child",
          service.collect_due(rng=random.Random(5)) == [])
    check("parents survived the ritual",
          dragons.get(a.id) is not None and dragons.get(b.id) is not None)

    print("7. The child works with the existing systems")
    fed2 = feeding.feed_unit(1, child.id, "meat")
    check("the child can be fed", fed2.success or fed2.reason == "full",
          fed2.reason)
    ures2 = up.apply(1, child.id, "power")
    check("the child can be upgraded", ures2.success,
          getattr(ures2, "reason", None))
    players.set_active_dragon(1, child.id)
    check("the child can be the active dragon",
          players.get_active_dragon_id(1) == child.id)
    from game.arena import rating
    check("the arena can rate the child", rating(dragons.get(child.id)) > 0)
    from handlers.dragon_manage import profile_text
    card = profile_text(dragons.get(child.id))
    check("the child renders on the dragon page", "🔮 عنصر:" in card, card)
    check("the child's card shows a rarity", "✨ کمیابی:" in card, card)

    print("8. Outcome chances are 70 / 25 / 5")
    counts = Counter(roll_outcome(random.Random(i)) for i in range(30000))
    for outcome, target in ((OUTCOME_INHERIT, 70), (OUTCOME_HYBRID, 25),
                            (OUTCOME_MUTATION, 5)):
        observed = counts[outcome] / 30000 * 100
        check(f"{outcome} ≈ {target}% (got {observed:.1f}%)",
              abs(observed - target) < 1.5, observed)
    check("outcome weights total 100",
          config.BREEDING_OUTCOME_INHERIT + config.BREEDING_OUTCOME_HYBRID
          + config.BREEDING_OUTCOME_MUTATION == 100)

    print("9. Hybrid combinations match the spec")
    for pa, pb, expected in (("fire", "ice", "lava"),
                             ("fire", "lightning", "storm"),
                             ("ice", "lightning", "blizzard"),
                             ("shadow", "fire", "inferno_shadow")):
        check(f"{pa}+{pb} -> {expected}", hybrid_for(pa, pb) == expected,
              hybrid_for(pa, pb))
        check(f"{pb}+{pa} is the same (order-free)",
              hybrid_for(pb, pa) == expected)
        check(f"{expected} is a real dragon type", expected in config.DRAGON_TYPES)
    check("identical elements have no hybrid", hybrid_for("fire", "fire") is None)
    check("an unpaired combination has no hybrid",
          hybrid_for("green", "golden") is None)
    check("hybrids can never hatch from an egg", all(
        h not in (set(e.get("dragons") or {}) | {e.get("element")})
        for e in config.EGG_TYPES.values() for h in config.HYBRID_DRAGON_TYPES))

    print("10. Hybrid outcome produces the hybrid element")
    pf = mk(dragons, players, 1, "آتشین", level=12, dtype="fire")
    pi = mk(dragons, players, 1, "یخی", level=12, dtype="ice")
    plan = plan_child(pf, pi, rng=random.Random(1), outcome=OUTCOME_HYBRID)
    check("fire+ice hybrid is a lava dragon", plan.dragon_type == "lava",
          plan.dragon_type)
    check("a hybrid is not flagged as mutated", not plan.mutated)
    # A pair with no hybrid must fall back to inheriting.
    pg = mk(dragons, players, 1, "سبز", level=12, dtype="green")
    pgo = mk(dragons, players, 1, "طلا", level=12, dtype="golden")
    fallback = plan_child(pg, pgo, rng=random.Random(2), outcome=OUTCOME_HYBRID)
    check("a pair with no hybrid falls back to inheritance",
          fallback.outcome == OUTCOME_INHERIT
          and fallback.dragon_type in {"green", "golden"},
          (fallback.outcome, fallback.dragon_type))

    print("11. Mutations are rarer and stronger")
    check("bump_rarity climbs the ladder",
          bump_rarity("normal") == "rare" and bump_rarity("rare") == "epic")
    check("bump_rarity clamps at mythical", bump_rarity("mythical") == "mythical")
    p1 = mk(dragons, players, 1, "پدر", level=12, rarity="rare", dtype="fire")
    p2 = mk(dragons, players, 1, "مادر", level=12, rarity="rare", dtype="ice")
    mut = plan_child(p1, p2, rng=random.Random(3), outcome=OUTCOME_MUTATION)
    check("a mutation is flagged", mut.mutated)
    check("a mutation is rarer than its parents",
          rarity_order(mut.rarity) > rarity_order("rare"), mut.rarity)
    base_hp, base_pw = scaled_stats(mut.rarity)
    check("a mutation gets +30% HP",
          mut.max_hp == int(round(base_hp * 1.30)), (mut.max_hp, base_hp))
    check("a mutation gets +30% power",
          mut.power == int(round(base_pw * 1.30)), (mut.power, base_pw))
    check("a mutation beats a plain dragon of the same rarity",
          mut.max_hp > base_hp and mut.power > base_pw)
    top = mk(dragons, players, 1, "اسطوره", level=12, rarity="mythical")
    top2 = mk(dragons, players, 1, "اسطوره۲", level=12, rarity="mythical",
              dtype="ice")
    capped = plan_child(top, top2, rng=random.Random(4), outcome=OUTCOME_MUTATION)
    check("a mythical pair's mutation stays mythical",
          capped.rarity == "mythical", capped.rarity)

    print("12. Inherited children take a parent's traits")
    for seed in range(30):
        plan = plan_child(p1, p2, rng=random.Random(seed), outcome=OUTCOME_INHERIT)
        if plan.dragon_type not in {"fire", "ice"}:
            check("inherited element comes from a parent", False, plan.dragon_type)
            break
        if plan.rarity not in {"rare"}:
            check("inherited rarity comes from a parent", False, plan.rarity)
            break
    else:
        check("inherited element comes from a parent", True)
        check("inherited rarity comes from a parent", True)
    check("an inherited child is not mutated",
          not plan_child(p1, p2, rng=random.Random(6),
                         outcome=OUTCOME_INHERIT).mutated)

    print("13. Not enough aether")
    players.get_or_create(4, "Poor")
    pa1 = mk(dragons, players, 4, "فقیر۱", level=12)
    pa2 = mk(dragons, players, 4, "فقیر۲", level=12)
    poor = service.start(4, pa1.id, pa2.id)
    check("a broke player cannot breed",
          not poor.ok and poor.reason == REASON_NOT_ENOUGH_AETHER, poor.reason)
    check("nothing was locked", dragons.get(pa1.id).breeding_status == "idle")
    check("aether never goes negative", players.get(4).aether >= 0)

    print("14. Concurrency — a double tap cannot start two rituals")
    players.get_or_create(5, "Tapper")
    players.add_resources(5, aether=1000)
    t1 = mk(dragons, players, 5, "تپ۱", level=12)
    t2 = mk(dragons, players, 5, "تپ۲", level=12)
    aether_before = players.get(5).aether
    outcomes = [service.start(5, t1.id, t2.id) for _ in range(5)]
    ok_count = sum(1 for o in outcomes if o.ok)
    check("exactly one ritual started", ok_count == 1, ok_count)
    spent = aether_before - players.get(5).aether
    check("charged exactly once", spent == outcomes[0].cost, (spent, outcomes[0].cost))
    check("only one active ritual exists", service.active(5) is not None)
    check("no aether leaked on refused attempts",
          spent == pair_cost(t1.rarity, t2.rarity), spent)

    print("15. UI")
    menu_btns = labels(bh.menu_keyboard())
    check("menu has the two selection buttons and back",
          menu_btns == ["🐉 انتخاب اژدهای اول", "🐉 انتخاب اژدهای دوم", "🔙 برگشت"],
          menu_btns)
    text = bh.menu_text(None, None, 120)
    check("menu title is «🧬 آیین پیوند اژدها»",
          text.startswith("🧬 آیین پیوند اژدها"), text)
    check("menu explains the system", "ترکیب" in text, text)
    check("menu shows the aether balance", "۱۲۰" in text, text)
    confirm_btns = labels(bh.menu_keyboard(can_confirm=True))
    check("a complete pair reveals the confirm button",
          "✅ شروع آیین" in confirm_btns, confirm_btns)

    # Live callback walkthrough for a fresh player.
    players.get_or_create(7, "UiUser")
    players.add_resources(7, aether=200)
    u1 = mk(dragons, players, 7, "یو۱", level=12, dtype="fire")
    u2 = mk(dragons, players, 7, "یو۲", level=12, dtype="ice")
    u_low = mk(dragons, players, 7, "یو-کم", level=2)
    uctx = type("C", (), {
        "bot_data": {"breeding_service": service, "player_repo": players},
        "user_data": {},
    })()

    q = FakeQuery(7, "bd:home")
    run(bh.breeding_callback(type("U", (), {"callback_query": q})(), uctx))
    check("home renders the menu", q.text and q.text.startswith("🧬"), q.text)

    q = FakeQuery(7, "bd:pick1")
    run(bh.breeding_callback(type("U", (), {"callback_query": q})(), uctx))
    check("the chooser lists dragons", q.markup is not None)
    check("the chooser marks under-level dragons",
          any("⛔" in b for b in labels(q.markup)), labels(q.markup))

    q = FakeQuery(7, f"bd:set1:{u1.id}")
    run(bh.breeding_callback(type("U", (), {"callback_query": q})(), uctx))
    check("slot 1 is filled", uctx.user_data.get(bh.KEY_FIRST) == u1.id)
    q = FakeQuery(7, f"bd:set2:{u1.id}")
    run(bh.breeding_callback(type("U", (), {"callback_query": q})(), uctx))
    check("the same dragon cannot fill both slots",
          uctx.user_data.get(bh.KEY_SECOND) is None and q.alerts, q.alerts)
    q = FakeQuery(7, f"bd:set2:{u_low.id}")
    run(bh.breeding_callback(type("U", (), {"callback_query": q})(), uctx))
    check("an under-level dragon is rejected with a toast",
          uctx.user_data.get(bh.KEY_SECOND) is None and q.alerts, q.alerts)
    q = FakeQuery(7, f"bd:set2:{u2.id}")
    run(bh.breeding_callback(type("U", (), {"callback_query": q})(), uctx))
    check("slot 2 is filled", uctx.user_data.get(bh.KEY_SECOND) == u2.id)
    check("the menu now offers confirm", "✅ شروع آیین" in labels(q.markup),
          labels(q.markup))

    q = FakeQuery(7, "bd:confirm")
    run(bh.breeding_callback(type("U", (), {"callback_query": q})(), uctx))
    check("confirming starts the ritual",
          q.text and "🧬 آیین پیوند شروع شد!" in q.text, q.text)
    check("the start card shows both parents",
          "یو۱" in q.text and "یو۲" in q.text, q.text)
    check("the start card shows the countdown",
          "زمان باقی‌مانده" in q.text and "ساعت" in q.text, q.text)
    check("the selection was cleared",
          uctx.user_data.get(bh.KEY_FIRST) is None)

    q = FakeQuery(7, "bd:home")
    run(bh.breeding_callback(type("U", (), {"callback_query": q})(), uctx))
    check("re-opening shows the in-progress screen",
          q.text and "آیین در جریانه" in q.text, q.text)

    q = FakeQuery(7, "bd:bogus")
    run(bh.breeding_callback(type("U", (), {"callback_query": q})(), uctx))
    check("unknown actions are ignored", q.text is None)

    print("16. Result card")
    from handlers.breeding import result_text
    card = result_text(result)
    check("result title", card.startswith("🎉 آیین پیوند موفق بود!"), card)
    check("result shows the new dragon", "🐉 اژدهای جدید:" in card, card)
    check("result shows element", "🔮 عنصر:" in card, card)
    check("result shows rarity", "✨ کمیابی:" in card, card)
    check("result shows HP and power",
          "❤️ HP:" in card and "⚔️ قدرت:" in card, card)

    print("17. Other systems still work")
    check("cold storage works", storage.contents(1).meat >= 0)
    from game.market import MarketService
    check("market works", MarketService(players=players).balance(1) > 0)
    from game.tools import ToolService
    check("tools work", ToolService(players=players).level(1, "rod") >= 1)
    tre = TreasuryService(players=players)
    check("treasury works", tre.contents(1).obsidian > 0)
    check("treasury lists eggs", len(tre.contents(1).eggs) == len(config.EGG_TYPES))
    from game.actions import fish, hunt
    gatherer, _ = players.get_or_create(11, "Gatherer")
    hres = hunt(players, gatherer)
    check("hunting works", hres.success, getattr(hres, "reason", None))
    fres = fish(players, players.get(11))
    check("fishing works", fres.success, getattr(fres, "reason", None))
    from game.eggs import EggService
    es = EggService()
    egg = es.spawn_wild_egg(-901)
    check("egg spawning works", egg is not None)
    if egg is not None:
        claimed, _ = es.claim_egg(egg.id, 11)
        check("egg claiming works", claimed is not None)
    check("currency intact", players.get(1).obsidian > 0)
    arena2 = ArenaService(players=players, dragons=dragons,
                          dragon_service=dragon_service)
    check("arena stats still render", arena2.stats(1)["limit"] == 10)

    print("18. Migration from a V8 database")
    _migration_test()

    print()
    total = PASSED + FAILED
    if FAILED:
        print(f"❌ {FAILED} of {total} checks failed")
        sys.exit(1)
    print(f"All breeding tests passed ✅  ({PASSED}/{total} checks)")


def _migration_test() -> None:
    """A V8 database (no breeding columns/table) upgrades in place."""
    import json
    import subprocess

    old = Path(tempfile.mkdtemp()) / "v8.db"
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
            arena_last_day TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE dragons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL,
            name TEXT NOT NULL, dragon_type TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1, xp INTEGER NOT NULL DEFAULT 0,
            hp INTEGER NOT NULL DEFAULT 100, max_hp INTEGER NOT NULL DEFAULT 100,
            power INTEGER NOT NULL DEFAULT 20, hunger INTEGER NOT NULL DEFAULT 100,
            rarity TEXT NOT NULL DEFAULT 'normal',
            last_fed_time REAL, is_test INTEGER NOT NULL DEFAULT 0,
            from_egg_id INTEGER, born_at TEXT);
        INSERT INTO players (user_id, username, meat, fish, obsidian, aether,
                             rod_level, weapon_level, arena_points)
        VALUES (4242, 'Veteran', 300, 250, 12000, 33, 6, 8, 900);
        INSERT INTO dragons (owner_id, name, dragon_type, level, xp, hp, max_hp,
                             power, hunger, rarity)
        VALUES (4242, 'کهنه‌کار', 'shadow', 20, 55, 400, 500, 210, 90, 'epic');
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
init_db(); run_migrations()
d = DragonRepository().list_by_owner(4242)[0]
p = PlayerRepository().get(4242)
with sqlite3.connect(%r) as c:
    tables = sorted(r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))
print(json.dumps({
    "name": d.name, "level": d.level, "xp": d.xp, "hp": d.hp,
    "max_hp": d.max_hp, "power": d.power, "hunger": d.hunger,
    "rarity": d.rarity, "type": d.dragon_type,
    "breeding_status": d.breeding_status,
    "finish": d.breeding_finish_time,
    "p1": d.parent_dragon_1, "p2": d.parent_dragon_2,
    "meat": p.meat, "fish": p.fish, "obsidian": p.obsidian, "aether": p.aether,
    "rod": p.rod_level, "weapon": p.weapon_level, "points": p.arena_points,
    "tables": tables,
}))
""" % (str(Path(__file__).resolve().parent.parent), str(old))

    env = dict(os.environ, DRAGON_DB_PATH=str(old), DRAGON_BOT_TOKEN="t:t")
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env
    )
    if proc.returncode != 0:
        check("V8 migration ran", False, proc.stderr[-500:])
        return
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    check("existing dragon survived", out["name"] == "کهنه‌کار", out["name"])
    check("existing dragon defaults to idle",
          out["breeding_status"] == "idle", out["breeding_status"])
    check("no stale finish time", out["finish"] is None)
    check("no stale parents", out["p1"] is None and out["p2"] is None)
    check("existing dragon keeps its level/XP",
          (out["level"], out["xp"]) == (20, 55))
    check("existing dragon keeps its HP",
          (out["hp"], out["max_hp"]) == (400, 500))
    check("existing dragon keeps its power", out["power"] == 210)
    check("existing dragon keeps its rarity", out["rarity"] == "epic")
    check("existing dragon keeps its element", out["type"] == "shadow")
    check("player food kept", (out["meat"], out["fish"]) == (300, 250))
    check("player currency kept", (out["obsidian"], out["aether"]) == (12000, 33))
    check("player tools kept", (out["rod"], out["weapon"]) == (6, 8))
    check("arena points kept", out["points"] == 900)
    check("breedings table created", "breedings" in out["tables"], out["tables"])


if __name__ == "__main__":
    main()
