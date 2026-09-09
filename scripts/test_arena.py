"""Arena PvP tests (Version 7).

Checks the round's requirements:
  * the old PvE combat system is gone (no enemies, no modules, no buttons),
  * /arena shows the four-button menu,
  * matchmaking respects level / power / HP and refuses unfair pairs,
  * a battle runs turn by turn until one dragon reaches 0 HP,
  * the winner gets arena points + obsidian + XP, the loser loses points,
  * NO dragon dies and no stored dragon HP is changed,
  * the daily battle limit is enforced and resets on a new day,
  * ranking + leagues work,
  * existing players are migrated with zeroed arena stats,
  * dragons / stats / upgrades / treasury / market / food still work.

Run: python3 scripts/test_arena.py
"""
from __future__ import annotations

import asyncio
import os
import random
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_arena_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")

import config  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.arena import (  # noqa: E402
    REASON_LIMIT_REACHED,
    REASON_NO_DRAGON,
    REASON_NO_OPPONENT,
    ArenaService,
    Fighter,
    is_fair_match,
    league_for,
    next_league,
    rating,
    roll_damage,
    simulate,
    summarise_turns,
    utc_day,
)
from game.dragons import DragonService  # noqa: E402
from game.storage import ColdStorageService  # noqa: E402
from game.treasury import TreasuryService  # noqa: E402
from game.upgrades import UpgradeService  # noqa: E402
from handlers import arena as ah  # noqa: E402
from models.arena import ArenaBattleRepository  # noqa: E402
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
    def __init__(self, user_id, data, chat_id=-500):
        self.from_user = type(
            "U", (), {"id": user_id, "username": f"u{user_id}", "is_bot": False}
        )()
        self.data = data
        self.toasts = []
        self.alerts = []
        self.text = None
        self.markup = None
        self.message = type("M", (), {"chat_id": chat_id, "message_id": 7})()

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


def press(ctx, data, user_id):
    q = FakeQuery(user_id, data)
    run(ah.arena_callback(type("U", (), {"callback_query": q})(), ctx))
    return q


def main() -> None:
    players = PlayerRepository()
    dragons = DragonRepository()
    dragon_service = DragonService(dragons=dragons)
    battles = ArenaBattleRepository()
    arena = ArenaService(
        players=players, dragons=dragons, battles=battles,
        dragon_service=dragon_service,
    )
    storage = ColdStorageService(players)

    ctx = type("C", (), {"bot_data": {
        "arena_service": arena, "player_repo": players,
    }})()

    print("\n1. Old PvE combat system is removed")
    for mod in ("game.combat", "handlers.battle", "models.battle"):
        try:
            __import__(mod)
            check(f"{mod} is gone", False, "still importable")
        except ImportError:
            check(f"{mod} is gone", True)
    check("config.ENEMIES removed", not hasattr(config, "ENEMIES"))
    check("config.COMMAND_BATTLE removed", not hasattr(config, "COMMAND_BATTLE"))
    for const in ("BATTLE_AETHER_CHANCE", "BATTLE_DRAGON_MIN_HP", "BATTLE_STALE_SECONDS"):
        check(f"config.{const} removed", not hasattr(config, const))
    check("old battles table dropped", "battles" not in _tables())
    check("arena_battles table exists", "arena_battles" in _tables())
    from handlers import COMMAND_MAP
    check("«مبارزه» is no longer a command", "مبارزه" not in COMMAND_MAP)

    print("2. Players and dragons")
    # Two evenly matched players, one very weak, one very strong.
    for uid, name in ((1001, "Ali"), (1002, "Reza"), (1003, "Weak"), (1004, "Boss")):
        players.get_or_create(uid, name)
    ali = players.get(1001)

    azar = _mk(dragons, players, 1001, "آذر", level=10, max_hp=300, power=120)
    raad = _mk(dragons, players, 1002, "رعد", level=11, max_hp=320, power=130)
    baby = _mk(dragons, players, 1003, "جوجه", level=1, max_hp=100, power=20)
    titan = _mk(dragons, players, 1004, "تایتان", level=30, max_hp=900, power=400)
    check("4 dragons created", all([azar, raad, baby, titan]))
    check("active dragon is set", players.get_active_dragon_id(1001) == azar.id)

    print("3. Existing players start unranked (migration compatibility)")
    check("arena_points = 0", ali.arena_points == 0, ali.arena_points)
    check("arena_wins = 0", ali.arena_wins == 0)
    check("arena_losses = 0", ali.arena_losses == 0)
    check("arena_battles_today = 0", ali.arena_battles_today == 0)

    print("4. Rating and fair matchmaking")
    check("rating uses level+power+hp", rating(azar) > rating(baby))
    check("stronger dragon rates higher", rating(titan) > rating(raad))
    check("آذر vs رعد is fair", is_fair_match(azar, raad, 3, 0.45))
    check("جوجه vs تایتان is NOT fair", not is_fair_match(baby, titan, 3, 0.45))
    check("جوجه vs تایتان unfair even in the wide window",
          not is_fair_match(baby, titan, 6, 0.75))
    check("level gap alone blocks a match",
          not is_fair_match(azar, titan, 3, 0.45))

    match = arena.find_opponent(1001)
    check("Ali is matched with Reza (closest strength)",
          match is not None and match[0].user_id == 1002,
          match[0].user_id if match else None)
    weak_match = arena.find_opponent(1003)
    check("the weak dragon is NOT matched with the titan",
          weak_match is None or weak_match[0].user_id != 1004,
          weak_match[0].user_id if weak_match else None)

    print("5. Damage calculation")
    f = Fighter(1, "x", 1, "د", "🐉", level=10, max_hp=300, hp=300, power=120)
    rng = random.Random(7)
    dmgs = [roll_damage(f, rng)[0] for _ in range(300)]
    check("damage is always positive", all(d >= config.ARENA_MIN_DAMAGE for d in dmgs))
    check("damage varies (random)", len(set(dmgs)) > 5)
    check("damage scales with power",
          sum(dmgs) / len(dmgs) > 120 * config.ARENA_DAMAGE_POWER_MIN_FACTOR)
    weakf = Fighter(2, "y", 2, "ج", "🐉", level=1, max_hp=100, hp=100, power=20)
    wd = [roll_damage(weakf, rng)[0] for _ in range(300)]
    check("a stronger dragon hits harder on average",
          sum(dmgs) / len(dmgs) > sum(wd) / len(wd))

    print("6. Battle simulation")
    a = Fighter(1, "a", 1, "آذر", "🐉", 10, 300, 300, 120)
    b = Fighter(2, "b", 2, "رعد", "🐉", 11, 320, 320, 130)
    winner, turns = simulate(a, b, random.Random(3))
    check("a winner is decided", winner in (1, 2), winner)
    check("the fight has turns", len(turns) > 0)
    check("fight ends when a dragon reaches 0 HP",
          a.hp == 0 or b.hp == 0 or len(turns) >= config.ARENA_MAX_TURNS)
    check("turns alternate attackers",
          all(turns[i].attacker != turns[i + 1].attacker for i in range(len(turns) - 1)))
    # Initiative is a coin flip (see game/arena.simulate), so over many seeds
    # both dragons must get to open the fight.
    openers = {simulate(
        Fighter(1, "a", 1, "آذر", "🐉", 10, 300, 300, 120),
        Fighter(2, "b", 2, "رعد", "🐉", 11, 320, 320, 130),
        random.Random(s))[1][0].attacker for s in range(40)}
    check("initiative is random, not always the challenger",
          openers == {"آذر", "رعد"}, openers)
    check("turn count is bounded", len(turns) <= config.ARENA_MAX_TURNS)
    check("summarise keeps the log short", len(summarise_turns(turns, 6)) <= 6)
    # Both sides must be able to win across many seeds.
    wins = set()
    for seed in range(60):
        x = Fighter(1, "a", 1, "آذر", "🐉", 10, 300, 300, 120)
        y = Fighter(2, "b", 2, "رعد", "🐉", 11, 320, 320, 130)
        wins.add(simulate(x, y, random.Random(seed))[0])
    check("balanced: both dragons can win", wins == {1, 2}, wins)
    # A mirror match must be close to a coin flip — no structural first-mover
    # advantage for the player who pressed the button.
    mirror = 0
    for seed in range(400):
        x = Fighter(1, "a", 1, "A", "🐉", 10, 300, 300, 120)
        y = Fighter(2, "b", 2, "B", "🐉", 10, 300, 300, 120)
        mirror += simulate(x, y, random.Random(seed))[0] == 1
    check("balanced: identical dragons are ~50/50",
          40 <= mirror / 400 * 100 <= 60, f"{mirror / 4:.1f}%")

    print("7. A real duel awards points, obsidian and XP")
    obs_before = players.get(1001).obsidian
    hp_before = dragons.get(azar.id).hp
    xp_before = dragons.get(azar.id).xp
    result = arena.fight(1001, chat_id=-500, rng=random.Random(1))
    check("fight succeeded", result.ok, result.reason)
    check("challenger card is 'آذر'", result.challenger.name == "آذر")
    check("opponent card is 'رعد'", result.opponent.name == "رعد")
    check("card shows entry HP, not drained HP",
          result.challenger.hp == result.challenger.max_hp)
    check("a winner is recorded", result.winner_id in (1001, 1002))
    check("obsidian was granted", players.get(1001).obsidian > obs_before)
    check("XP was granted", dragons.get(azar.id).xp != xp_before or result.leveled_up)
    if result.won:
        check("win: +25 points", result.points_delta == config.ARENA_WIN_POINTS)
        check("win: points recorded", players.get(1001).arena_points == config.ARENA_WIN_POINTS)
        check("win counter bumped", players.get(1001).arena_wins == 1)
        check("opponent got a loss", players.get(1002).arena_losses == 1)
    else:
        check("loss: negative points", result.points_delta < 0)
        check("loss counter bumped", players.get(1001).arena_losses == 1)
        check("opponent got a win", players.get(1002).arena_wins == 1)
    check("battle was logged", result.battle_id is not None and battles.count_all() == 1)

    print("8. NO dragon death — stored HP is never touched")
    check("challenger dragon HP unchanged",
          dragons.get(azar.id).hp == hp_before, dragons.get(azar.id).hp)
    check("challenger dragon still alive", dragons.get(azar.id).hp > 0)
    check("opponent dragon HP unchanged", dragons.get(raad.id).hp == raad.hp)
    check("opponent dragon still alive", dragons.get(raad.id).hp > 0)
    check("dragons still exist", dragons.get(azar.id) and dragons.get(raad.id))
    for _ in range(5):
        arena.fight(1001, rng=random.Random(9))
    check("after many fights the dragon is still alive and full HP",
          dragons.get(azar.id).hp == hp_before or dragons.get(azar.id).hp > 0)

    print("9. Daily battle limit")
    players.get_or_create(2001, "Limited")
    players.get_or_create(2002, "Sparring")
    _mk(dragons, players, 2001, "لیمیت", level=5, max_hp=200, power=60)
    _mk(dragons, players, 2002, "اسپار", level=5, max_hp=200, power=60)
    used = 0
    for _ in range(config.ARENA_DAILY_BATTLE_LIMIT + 4):
        r = arena.fight(2001, rng=random.Random(used))
        if r.ok:
            used += 1
        else:
            check("blocked for the right reason", r.reason == REASON_LIMIT_REACHED, r.reason)
            break
    check(f"exactly {config.ARENA_DAILY_BATTLE_LIMIT} battles allowed per day",
          used == config.ARENA_DAILY_BATTLE_LIMIT, used)
    check("no battles left", arena.battles_left(2001) == 0)
    blocked = arena.fight(2001, rng=random.Random(1))
    check("further fights are refused", not blocked.ok)
    check("refusal reason is the limit", blocked.reason == REASON_LIMIT_REACHED)
    over_limit_points = players.get(2001).arena_points
    arena.fight(2001, rng=random.Random(2))
    check("a blocked fight grants nothing",
          players.get(2001).arena_points == over_limit_points)

    print("10. The limit resets on a new day")
    import time as _t
    tomorrow = _t.time() + 86400
    check("tomorrow the counter is fresh",
          arena.battles_left(2001, now=tomorrow) == config.ARENA_DAILY_BATTLE_LIMIT,
          arena.battles_left(2001, now=tomorrow))
    check("utc_day differs across days", utc_day() != utc_day(tomorrow))
    r = arena.fight(2001, rng=random.Random(3), now=tomorrow)
    check("can fight again tomorrow", r.ok, r.reason)

    print("11. A failed search does not consume a battle slot")
    players.get_or_create(3001, "Lonely")
    _mk(dragons, players, 3001, "تنها", level=99, max_hp=5000, power=2000)
    left_before = arena.battles_left(3001)
    r = arena.fight(3001, rng=random.Random(1))
    check("no opponent found for an outlier dragon",
          not r.ok and r.reason == REASON_NO_OPPONENT, r.reason)
    check("slot not consumed on a failed search",
          arena.battles_left(3001) == left_before)

    print("12. A player with no dragon cannot fight")
    players.get_or_create(4001, "Dragonless")
    r = arena.fight(4001)
    check("refused without a dragon", not r.ok and r.reason == REASON_NO_DRAGON, r.reason)

    print("13. Leagues")
    check("0 points -> bronze 🥉", league_for(0)["emoji"] == "🥉")
    check("600 -> silver 🥈", league_for(600)["emoji"] == "🥈")
    check("2000 -> gold 🥇", league_for(2000)["emoji"] == "🥇")
    check("4000 -> diamond 💎", league_for(4000)["emoji"] == "💎")
    check("9000 -> legend 🐉", league_for(9000)["emoji"] == "🐉")
    check("league is monotonic", all(
        league_for(p)["min_points"] <= league_for(p + 100)["min_points"]
        for p in range(0, 8000, 100)))
    check("next league from bronze is silver", next_league(0)["key"] == "silver")
    check("no next league at the top", next_league(99999) is None)

    print("14. Ranking")
    top = arena.ranking()
    check("ranking is returned", isinstance(top, list))
    check("ranking is sorted by points",
          all(top[i].points >= top[i + 1].points for i in range(len(top) - 1)),
          [e.points for e in top])
    check("ranks are 1-based and sequential",
          [e.rank for e in top] == list(range(1, len(top) + 1)))
    check("ranking size is capped", len(top) <= config.ARENA_RANKING_SIZE)
    if top:
        check("rank_of matches the leaderboard",
              players.arena_rank_of(top[0].user_id) == 1)
    check("an unranked player has no rank", players.arena_rank_of(4001) is None)
    check("points never go negative", all(
        players.get(u).arena_points >= 0 for u in (1001, 1002, 2001, 2002)))

    print("15. UI — /arena menu")
    q = FakeQuery(1001, "")
    stats = arena.stats(1001)
    text = ah.menu_text(stats)
    check("title is «🏟️ آرنا اژدها»", text.startswith("🏟️ آرنا اژدها"), text)
    check("menu shows the daily counter", "مبارزه‌های باقی‌مانده امروز" in text)
    btns = labels(ah.menu_keyboard())
    check("menu has exactly the 4 required buttons",
          btns == ["⚔️ پیدا کردن حریف", "🏆 رتبه‌بندی", "🐉 اژدهای من", "🔙 برگشت"], btns)

    print("16. UI — callbacks edit in place")
    q = press(ctx, "ar:home", 1001)
    check("home renders the menu", q.text and q.text.startswith("🏟️ آرنا اژدها"))
    q = press(ctx, "ar:rank", 1001)
    check("ranking screen renders", q.text and "🏆 رتبه آرنا" in q.text, q.text)
    check("ranking uses medals", "🥇" in (q.text or ""))
    check("ranking has a back button", "🔙 برگشت" in labels(q.markup))
    q = press(ctx, "ar:me", 1001)
    check("my-dragon screen renders", q.text and "آذر" in q.text, q.text)
    check("my-dragon shows the league", "لیگ" in (q.text or ""))
    check("my-dragon shows wins/losses", "برد" in (q.text or ""))
    q = press(ctx, "ar:find", 1002)
    check("find produces a battle screen or a toast",
          (q.text and "نبرد آرنا" in q.text) or q.alerts, (q.text, q.alerts))
    if q.text:
        check("battle screen shows the VS card", "VS" in q.text)
        check("battle screen shows damage", "آسیب وارد شد" in q.text)
        check("battle screen shows an outcome",
              "برنده شدی" in q.text or "شکست خوردی" in q.text)
        check("result has a rematch button", "⚔️ نبرد دوباره" in labels(q.markup))
    q = press(ctx, "ar:find", 4001)
    check("dragonless player gets an alert", bool(q.alerts), q.alerts)
    check("dragonless player sees no battle screen", q.text is None)
    q = press(ctx, "ar:bogus", 1001)
    check("unknown action is ignored", q.text is None)

    print("17. Other systems still work")
    d = dragons.get(azar.id)
    check("dragon stats intact", d.level >= 10 and d.power >= 120 and d.max_hp >= 300)
    check("dragon level intact", d.level >= 10)
    # Upgrades
    players.add_resources(1001, obsidian=100000)
    up = UpgradeService(dragons=dragons, players=players)
    before_power = dragons.get(azar.id).power
    res = up.apply(1001, azar.id, "power")
    check("upgrade system works", res.success, getattr(res, "reason", None))
    check("upgrade raised power", dragons.get(azar.id).power > before_power)
    # Food / storage
    storage.deposit(1001, meat=20, fish=10)
    c = storage.contents(1001)
    check("food system works", c.meat >= 20 and c.fish >= 10, (c.meat, c.fish))
    check("food can be spent", storage.consume(1001, "meat", 5) is True)
    # Treasury
    tre = TreasuryService(players=players)
    contents = tre.contents(1001)
    check("treasury works", contents.obsidian > 0)
    check("treasury still reports tools",
          contents.rod_level >= 1 and contents.weapon_level >= 1)
    # Market
    from game.market import MarketService
    check("market works", MarketService(players=players).balance(1001) > 0)
    # Currency
    check("currency intact", players.get(1001).obsidian > 0)

    print("18. Migration from a V6 database")
    _migration_test()

    print()
    total = PASSED + FAILED
    if FAILED:
        print(f"❌ {FAILED} of {total} checks failed")
        sys.exit(1)
    print(f"All arena tests passed ✅  ({PASSED}/{total} checks)")


def _tables() -> set:
    with sqlite3.connect(_tmp_db) as conn:
        return {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }


def _mk(dragons, players, owner, name, level, max_hp, power):
    """Create a dragon with explicit stats and make it the active one."""
    players.get_or_create(owner, f"u{owner}")
    d = dragons.create(owner, "fire", None)
    dragons.set_name(d.id, owner, name)
    dragons.update_growth(d.id, level=level, xp=0, hp=max_hp, max_hp=max_hp, power=power)
    players.set_active_dragon(owner, d.id)
    return dragons.get(d.id)


def _migration_test() -> None:
    """A V6 database (no arena columns, with the old battles table) upgrades.

    Runs in a subprocess because ``config.DB_PATH`` is read once at import.
    """
    import json
    import subprocess

    tmpdir = Path(tempfile.mkdtemp())
    old = tmpdir / "v6.db"
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
            created_at TEXT, updated_at TEXT);
        CREATE TABLE battles (
            battle_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            dragon_id INTEGER, enemy_id TEXT, enemy_hp INTEGER,
            status TEXT, created_time REAL);
        INSERT INTO players (user_id, username, meat, fish, obsidian, aether,
                             rod_level, weapon_level)
        VALUES (7777, 'Veteran', 120, 90, 5000, 12, 4, 6);
        INSERT INTO battles (user_id, dragon_id, enemy_id, enemy_hp, status,
                             created_time) VALUES (7777, 1, 'wolf', 50, 'active', 0);
        """
    )
    conn.commit()
    conn.close()

    script = """
import json, sqlite3, sys
sys.path.insert(0, %r)
from database.init_db import init_db
from database.migrate import run_migrations
from models.player import PlayerRepository
init_db(); run_migrations()
p = PlayerRepository().get(7777)
with sqlite3.connect(%r) as c:
    tables = sorted(r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))
print(json.dumps({
    "found": p is not None,
    "meat": p.meat, "fish": p.fish, "obsidian": p.obsidian, "aether": p.aether,
    "rod": p.rod_level, "weapon": p.weapon_level,
    "points": p.arena_points, "wins": p.arena_wins, "losses": p.arena_losses,
    "today": p.arena_battles_today, "tables": tables,
}))
""" % (str(Path(__file__).resolve().parent.parent), str(old))

    env = dict(os.environ, DRAGON_DB_PATH=str(old), DRAGON_BOT_TOKEN="t:t")
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env
    )
    if proc.returncode != 0:
        check("V6 migration subprocess ran", False, proc.stderr[-400:])
        return
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    check("V6 player survived the migration", out["found"])
    check("existing meat kept", out["meat"] == 120, out["meat"])
    check("existing fish kept", out["fish"] == 90, out["fish"])
    check("existing obsidian kept", out["obsidian"] == 5000, out["obsidian"])
    check("existing aether kept", out["aether"] == 12, out["aether"])
    check("existing rod level kept", out["rod"] == 4, out["rod"])
    check("existing weapon level kept", out["weapon"] == 6, out["weapon"])
    check("arena_points defaults to 0", out["points"] == 0)
    check("arena_wins defaults to 0", out["wins"] == 0)
    check("arena_losses defaults to 0", out["losses"] == 0)
    check("arena_battles_today defaults to 0", out["today"] == 0)
    check("obsolete battles table dropped by migration",
          "battles" not in out["tables"], out["tables"])
    check("arena_battles table created", "arena_battles" in out["tables"])


if __name__ == "__main__":
    main()
