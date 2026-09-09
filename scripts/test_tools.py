"""🎣 Fishing rod and 🏹 hunting weapon progression.

Covers the config tables, defaults for new AND existing players, reward
scaling, prey unlocking, paid upgrades, the level cap, atomicity, the market
screens and the treasury display.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")
os.environ["DRAGON_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "tools.db")

import config  # noqa: E402
from database.connection import get_db  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game import actions  # noqa: E402
from game.tools import (  # noqa: E402
    ROD,
    WEAPON,
    ToolService,
    allowed_prey,
    clamp_level,
    is_max_level,
    reward_range,
    tool_display,
    upgrade_cost,
)
from game.treasury import TreasuryService  # noqa: E402
from handlers import market as mk  # noqa: E402
from handlers import treasury as tr  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

RESULTS = []

# The costs and rewards required by the design.
ROD_SPEC = {
    1: (0, 5, 10), 2: (2000, 8, 15), 3: (5000, 12, 20), 4: (10000, 15, 25),
    5: (20000, 20, 30), 6: (35000, 25, 40), 7: (60000, 35, 50),
    8: (100000, 45, 65), 9: (170000, 60, 85), 10: (300000, 80, 120),
}
WEAPON_SPEC = {
    1: (0, 3, 6), 2: (2000, 5, 10), 3: (5000, 8, 15), 4: (10000, 12, 20),
    5: (20000, 18, 30), 6: (35000, 25, 40), 7: (60000, 35, 55),
    8: (100000, 50, 70), 9: (170000, 70, 100), 10: (300000, 100, 150),
}


def check(name, cond, extra=""):
    RESULTS.append(bool(cond))
    print(("✅" if cond else "❌"), name, ("→ " + str(extra)) if not cond else "")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FakeQuery:
    def __init__(self, user, data):
        self.from_user = user
        self.data = data
        self.answers = []
        self.edits = []
        self.message = type("M", (), {"message_id": 1, "chat_id": -100})()

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None, **kw):
        self.edits.append((text, reply_markup))


class FakeUser:
    def __init__(self, uid, name="P"):
        self.id = uid
        self.username = name
        self.full_name = name
        self.is_bot = False


def labels(markup):
    if markup is None:
        return []
    return [b.text for row in markup.inline_keyboard for b in row]


def main():
    init_db()
    run_migrations()

    players = PlayerRepository()
    tools = ToolService(players=players)

    # ---------- config tables ----------
    check("10 rod levels", len(config.FISHING_RODS) == 10)
    check("10 weapon levels", len(config.HUNTING_WEAPONS) == 10)
    check("TOOL_MAX_LEVEL is 10", config.TOOL_MAX_LEVEL == 10)

    for lvl, (cost, lo, hi) in ROD_SPEC.items():
        spec = config.FISHING_RODS[lvl]
        check(f"rod Lv.{lvl} costs {cost}", spec["cost"] == cost, spec["cost"])
        check(f"rod Lv.{lvl} rewards {lo}-{hi}",
              (spec["min"], spec["max"]) == (lo, hi), (spec["min"], spec["max"]))
    for lvl, (cost, lo, hi) in WEAPON_SPEC.items():
        spec = config.HUNTING_WEAPONS[lvl]
        check(f"weapon Lv.{lvl} costs {cost}", spec["cost"] == cost, spec["cost"])
        check(f"weapon Lv.{lvl} rewards {lo}-{hi}",
              (spec["min"], spec["max"]) == (lo, hi), (spec["min"], spec["max"]))

    check("rod rewards never shrink",
          all(config.FISHING_RODS[l + 1]["min"] > config.FISHING_RODS[l]["min"]
              for l in range(1, 10)))
    check("weapon rewards never shrink",
          all(config.HUNTING_WEAPONS[l + 1]["min"] > config.HUNTING_WEAPONS[l]["min"]
              for l in range(1, 10)))
    check("upgrade_cost matches the table",
          all(upgrade_cost(ROD, l) == ROD_SPEC[l + 1][0] for l in range(1, 10)))
    check("upgrade_cost is 0 at the cap", upgrade_cost(ROD, 10) == 0)

    # ---------- prey unlocking ----------
    check("Lv.1 weapon hunts only rabbit", allowed_prey(1) == ("rabbit",), allowed_prey(1))
    check("Lv.2 weapon adds deer",
          set(allowed_prey(2)) == {"rabbit", "deer"}, allowed_prey(2))
    check("Lv.3 weapon adds gazelle",
          set(allowed_prey(3)) == {"rabbit", "deer", "gazelle"}, allowed_prey(3))
    check("high levels keep the full roster",
          all(set(allowed_prey(l)) == {"rabbit", "deer", "gazelle"}
              for l in range(3, 11)))
    check("every prey key is real",
          all(k in config.HUNT_PREY for l in range(1, 11) for k in allowed_prey(l)))

    # ---------- defaults ----------
    new_user = 1001
    players.get_or_create(new_user, "new")
    check("new player rod is Lv.1", tools.level(new_user, ROD) == 1)
    check("new player weapon is Lv.1", tools.level(new_user, WEAPON) == 1)
    p = players.get(new_user)
    check("player row exposes rod_level", p.rod_level == 1)
    check("player row exposes weapon_level", p.weapon_level == 1)

    # existing player (row created before the migration) also gets Lv.1
    with get_db() as conn:
        conn.execute(
            "INSERT INTO players (user_id, username, obsidian) VALUES (?, ?, ?)",
            (1002, "legacy", 0),
        )
    check("pre-existing player defaults to rod Lv.1", tools.level(1002, ROD) == 1)
    check("pre-existing player defaults to weapon Lv.1", tools.level(1002, WEAPON) == 1)

    # ---------- clamping ----------
    check("clamp below range", clamp_level(0) == 1 and clamp_level(-3) == 1)
    check("clamp above range", clamp_level(99) == 10)
    check("clamp junk", clamp_level(None) == 1 and clamp_level("x") == 1)
    check("is_max_level", is_max_level(10) and not is_max_level(9))

    # ---------- upgrading ----------
    u = 2001
    players.get_or_create(u, "rich")
    players.add_resources(u, obsidian=2000)

    res = tools.upgrade(u, ROD)
    check("rod upgrade succeeds with exact funds", res.success, res.reason)
    check("rod upgrade charges 2000", res.spent == 2000, res.spent)
    check("rod level 1 ➜ 2", (res.previous_level, res.level) == (1, 2), res)
    check("balance is now 0", players.get(u).obsidian == 0)
    check("level persisted in the DB", players.get(u).rod_level == 2)
    check("result reports the next cost", res.next_cost == 5000, res.next_cost)
    check("weapon untouched by a rod upgrade", players.get(u).weapon_level == 1)

    # too poor
    res = tools.upgrade(u, ROD)
    check("upgrade refused when poor",
          not res.success and res.reason == "not_enough", res.reason)
    check("refusal reports the shortfall", res.missing == 5000, res.missing)
    check("no obsidian taken on refusal", players.get(u).obsidian == 0)
    check("level unchanged on refusal", players.get(u).rod_level == 2)

    # ---------- the cap ----------
    capped = 3001
    players.get_or_create(capped, "capped")
    players.add_resources(capped, obsidian=10_000_000)
    for expected in range(2, 11):
        r = tools.upgrade(capped, WEAPON)
        check(f"weapon reaches Lv.{expected}", r.success and r.level == expected, r)
    check("weapon is at the cap", players.get(capped).weapon_level == 10)
    r = tools.upgrade(capped, WEAPON)
    check("cannot upgrade past Lv.10",
          not r.success and r.reason == "max_level", r.reason)
    check("no obsidian spent at the cap",
          players.get(capped).obsidian == 10_000_000 - sum(
              WEAPON_SPEC[l][0] for l in range(2, 11)))
    check("still Lv.10 after a refused upgrade", players.get(capped).weapon_level == 10)

    # ---------- atomicity ----------
    race = 4001
    players.get_or_create(race, "race")
    players.add_resources(race, obsidian=2000)   # enough for exactly ONE upgrade
    outcomes = []

    def tap():
        outcomes.append(ToolService(players=PlayerRepository()).upgrade(race, ROD))

    threads = [threading.Thread(target=tap) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wins = [o for o in outcomes if o.success]
    check("10 simultaneous taps -> exactly one upgrade", len(wins) == 1, len(wins))
    check("race: level went up by exactly 1", players.get(race).rod_level == 2)
    check("race: no overspend", players.get(race).obsidian == 0)

    # ---------- rewards scale with the tool ----------
    g = 5001
    player, _ = players.get_or_create(g, "gather")
    for _ in range(30):
        with get_db() as conn:
            conn.execute("UPDATE players SET last_fishing_time = NULL WHERE user_id = ?", (g,))
        fresh = players.get(g)
        r = actions.fish(players, fresh)
        lo, hi = reward_range(ROD, 1)
        if not (r.success and lo <= r.fish_gained <= hi):
            check("Lv.1 fishing stays in range", False, r)
            break
    else:
        check("Lv.1 fishing stays in range (5-10)", True)

    with get_db() as conn:
        conn.execute("UPDATE players SET rod_level = 10 WHERE user_id = ?", (g,))
    highs = []
    for _ in range(30):
        with get_db() as conn:
            conn.execute("UPDATE players SET last_fishing_time = NULL WHERE user_id = ?", (g,))
        r = actions.fish(players, players.get(g))
        highs.append(r.fish_gained)
    lo, hi = reward_range(ROD, 10)
    check("Lv.10 fishing stays in range (80-120)",
          all(lo <= v <= hi for v in highs), (min(highs), max(highs)))
    check("Lv.10 out-fishes Lv.1", min(highs) > ROD_SPEC[1][2], min(highs))
    with get_db() as conn:
        conn.execute("UPDATE players SET last_fishing_time = NULL WHERE user_id = ?", (g,))
    _r = actions.fish(players, players.get(g))
    check("fishing reports the rod level used",
          _r.success and _r.tool_level == 10, _r)

    # hunting
    h = 6001
    players.get_or_create(h, "hunter")
    caught = set()
    for _ in range(40):
        with get_db() as conn:
            conn.execute("UPDATE players SET last_hunt_time = NULL WHERE user_id = ?", (h,))
        r = actions.hunt(players, players.get(h))
        if r.success:
            caught.add(r.prey_key)
            lo, hi = reward_range(WEAPON, 1)
            if not lo <= r.meat_gained <= hi:
                check("Lv.1 hunting stays in range", False, r)
                break
    else:
        check("Lv.1 hunting stays in range (3-6)", True)
    check("Lv.1 only catches rabbits", caught == {"rabbit"}, caught)

    with get_db() as conn:
        conn.execute("UPDATE players SET weapon_level = 10 WHERE user_id = ?", (h,))
    caught10, meats = set(), []
    for _ in range(60):
        with get_db() as conn:
            conn.execute("UPDATE players SET last_hunt_time = NULL WHERE user_id = ?", (h,))
        r = actions.hunt(players, players.get(h))
        caught10.add(r.prey_key)
        meats.append(r.meat_gained)
    lo, hi = reward_range(WEAPON, 10)
    check("Lv.10 hunting stays in range (100-150)",
          all(lo <= m <= hi for m in meats), (min(meats), max(meats)))
    check("Lv.10 catches more prey types", len(caught10) > 1, caught10)
    check("Lv.10 out-hunts Lv.1", min(meats) > WEAPON_SPEC[1][2], min(meats))

    # ---------- market screens ----------
    user = FakeUser(7001)
    players.get_or_create(user.id, "shopper")
    players.add_resources(user.id, obsidian=2000)
    ctx = type("C", (), {"bot_data": {
        "player_repo": players,
        "tool_service": tools,
        "market_service": type("M", (), {"balance": staticmethod(lambda uid: 2000)})(),
    }})()

    home_labels = labels(mk.categories_keyboard())
    check("market has the fishing tools button",
          "🎣 ابزار ماهیگیری" in home_labels, home_labels)
    check("market has the hunting tools button",
          "🏹 ابزار شکار" in home_labels, home_labels)

    q = FakeQuery(user, "mk:cat:rod")
    run(mk.market_callback(type("U", (), {"callback_query": q})(), ctx))
    text, markup = q.edits[0]
    check("rod screen shows the current level", "Lv.۱" in text, text)
    check("rod screen shows «قلاب فعلی»", "قلاب فعلی" in text, text)
    check("rod screen has an upgrade button", "⬆️ ارتقا" in labels(markup), labels(markup))

    q = FakeQuery(user, "mk:cat:hunt")
    run(mk.market_callback(type("U", (), {"callback_query": q})(), ctx))
    text, markup = q.edits[0]
    check("weapon screen shows «ابزار شکار»", "ابزار شکار" in text, text)
    check("weapon screen has an upgrade button", "⬆️ ارتقا" in labels(markup))

    # upgrade through the market
    q = FakeQuery(user, "mk:toolup:rod")
    run(mk.market_callback(type("U", (), {"callback_query": q})(), ctx))
    text, _ = q.edits[0]
    check("market upgrade shows the success card",
          text.startswith("🎉 ارتقا موفق!"), text)
    check("success card shows the transition", "Lv.۱ ➜ Lv.۲" in text, text)
    check("market upgrade persisted", players.get(user.id).rod_level == 2)
    check("market upgrade charged", players.get(user.id).obsidian == 0)

    # too poor through the market
    q = FakeQuery(user, "mk:toolup:rod")
    run(mk.market_callback(type("U", (), {"callback_query": q})(), ctx))
    check("poor upgrade alerts «ابسیدین کافی نیست»",
          any(a and "ابسیدین کافی نیست" in a for a in q.answers), q.answers)
    check("poor upgrade did not level up", players.get(user.id).rod_level == 2)

    # maxed tool hides the button
    with get_db() as conn:
        conn.execute("UPDATE players SET rod_level = 10 WHERE user_id = ?", (user.id,))
    q = FakeQuery(user, "mk:cat:rod")
    run(mk.market_callback(type("U", (), {"callback_query": q})(), ctx))
    text, markup = q.edits[0]
    check("maxed rod hides the upgrade button",
          "⬆️ ارتقا" not in labels(markup), labels(markup))
    check("maxed rod says so", "حداکثر سطح" in text, text)

    # ---------- treasury ----------
    treasury = TreasuryService(players=players)
    contents = treasury.contents(user.id)
    check("treasury reports the rod level", contents.rod_level == 10, contents.rod_level)
    check("treasury reports the weapon level", contents.weapon_level == 1)
    check("treasury exposes the tool name",
          contents.rod_name == config.FISHING_RODS[10]["name"], contents.rod_name)
    ttext = tr.treasury_text(contents)
    check("treasury shows 🎣 قلاب", "🎣 قلاب: Lv.۱۰" in ttext, ttext)
    check("treasury shows 🏹 ابزار شکار", "🏹 ابزار شکار: Lv.۱" in ttext, ttext)
    check("treasury still shows currencies",
          "🪨 ابسیدین:" in ttext and "✨ اتر:" in ttext, ttext)

    # ---------- display helpers ----------
    check("tool_display returns rod names",
          tool_display(ROD, 1)[1] == config.FISHING_RODS[1]["name"])
    check("tool_display returns weapon names",
          tool_display(WEAPON, 10)[1] == config.HUNTING_WEAPONS[10]["name"])
    check("unknown kind raises", _raises(lambda: reward_range("nope", 1)))
    check("unknown tool column raises",
          _raises(lambda: players.get_tool_level(1, "obsidian")))
    check("upgrade of an unknown kind is refused",
          tools.upgrade(user.id, "nope").reason == "unknown")

    print()
    passed = sum(RESULTS)
    print(f"{passed}/{len(RESULTS)} checks passed")
    if passed == len(RESULTS):
        print("All tool progression tests passed ✅")
    return 0 if passed == len(RESULTS) else 1


def _raises(fn):
    try:
        fn()
    except Exception:
        return True
    return False


if __name__ == "__main__":
    sys.exit(main())
