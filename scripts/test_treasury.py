"""Dragon Treasury (خزانه): read-only inventory view.

Covers the command, all three screens, edit-in-place navigation, zero values,
error handling, and — most importantly — that the treasury reads the EXISTING
currency / cold-storage / egg data instead of duplicating it.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")
os.environ["DRAGON_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "treasury.db")

import config  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.chests import ChestService  # noqa: E402
from game.storage import ColdStorageService  # noqa: E402
from game.treasury import TreasuryService  # noqa: E402
from handlers import COMMAND_MAP, treasury as tr  # noqa: E402
from models.egg import EggRepository  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append(bool(cond))
    print(("✅" if cond else "❌"), name, ("→ " + str(extra)) if not cond else "")


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.replies.append((text, reply_markup))


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
    def __init__(self, uid=1, name="Ali"):
        self.id = uid
        self.username = name
        self.full_name = name
        self.is_bot = False


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def labels(markup):
    if markup is None:
        return []
    return [b.text for row in markup.inline_keyboard for b in row]


def datas(markup):
    if markup is None:
        return []
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def main():
    init_db()
    run_migrations()

    players = PlayerRepository()
    eggs = EggRepository()
    storage = ColdStorageService(players)
    treasury = TreasuryService(players=players, eggs=eggs, storage=storage)

    user = FakeUser()
    ctx = type("C", (), {
        "bot_data": {"player_repo": players, "treasury_service": treasury},
        "bot": None,
    })()

    # ---------- command registration ----------
    check("«خزانه» command constant exists", config.COMMAND_TREASURY == "خزانه")
    check("«خزانه» is routed", COMMAND_MAP.get("خزانه") is tr.treasury_command)
    check("treasury prefix does not collide",
          tr.PREFIX == "tr:" and all(
              not tr.PREFIX.startswith(p) and not p.startswith(tr.PREFIX)
              for p in ("dg:", "claim_egg:", "admin:", "open_chest:", "mk:", "bt:")))

    # ---------- empty player shows zeros ----------
    players.get_or_create(user.id, user.username)
    msg = FakeMessage()
    upd = type("U", (), {"effective_user": user, "effective_message": msg})()
    run(tr.treasury_command(upd, ctx))

    check("command replies once", len(msg.replies) == 1)
    text, markup = msg.replies[0]
    check("home title is 🏰 خزانه اژدها", text.startswith("🏰 خزانه اژدها"), text)
    check("home shows obsidian", "🪨 ابسیدین: ۰" in text, text)
    check("home shows aether", "✨ اتر: ۰" in text, text)
    check("zero is shown, not hidden", "۰" in text, text)
    check("home is short (title + 2 lines)",
          len([l for l in text.split("\n") if l.strip()]) == 3, text)
    check("home has the food button", "🥩 غذا" in labels(markup), labels(markup))
    check("home has the eggs button", "🥚 تخم‌ها" in labels(markup), labels(markup))
    check("home has no unnecessary buttons", len(labels(markup)) == 2, labels(markup))

    # ---------- reads REAL data from existing systems ----------
    players.add_resources(user.id, obsidian=1500, aether=7)
    storage.deposit(user.id, meat=50, fish=80)

    contents = treasury.contents(user.id)
    check("reads obsidian from players table", contents.obsidian == 1500, contents.obsidian)
    check("reads aether from players table", contents.aether == 7, contents.aether)
    check("reads meat from cold storage", contents.meat == 50, contents.meat)
    check("reads fish from cold storage", contents.fish == 80, contents.fish)

    # cross-check against the cold storage service itself (no duplicate store)
    cold = storage.contents(user.id)
    check("food matches ColdStorageService exactly",
          (contents.meat, contents.fish) == (cold.meat, cold.fish))
    player = players.get(user.id)
    check("currency matches the player row exactly",
          (contents.obsidian, contents.aether) == (player.obsidian, player.aether))

    # ---------- food screen ----------
    q = FakeQuery(user, "tr:food")
    run(tr.treasury_callback(type("U", (), {"callback_query": q})(), ctx))
    check("food press edits the message (no new message)", len(q.edits) == 1, q.edits)
    ftext, fmarkup = q.edits[0]
    check("food title is ❄️ سردخانه", ftext.startswith("❄️ سردخانه"), ftext)
    check("food shows meat", "🥩 گوشت: ۵۰" in ftext, ftext)
    check("food shows fish", "🐟 ماهی: ۸۰" in ftext, ftext)
    check("food screen has a back button", "🔙 برگشت" in labels(fmarkup), labels(fmarkup))
    check("food screen is short",
          len([l for l in ftext.split("\n") if l.strip()]) == 3, ftext)

    # ---------- eggs screen ----------
    q = FakeQuery(user, "tr:eggs")
    run(tr.treasury_callback(type("U", (), {"callback_query": q})(), ctx))
    etext, emarkup = q.edits[0]
    check("eggs title is 🥚 تخم‌های من:", etext.startswith("🥚 تخم‌های من:"), etext)
    check("eggs shows the common egg line with 0",
          "🥚 تخم معمولی: ۰" in etext, etext)
    check("eggs screen has a back button", "🔙 برگشت" in labels(emarkup))

    # Give the player two incubating COMMON eggs via the real egg system.
    # spawn_wild_egg() rolls a random type, so create the rows explicitly to
    # keep the assertion deterministic.
    import time as _t
    for i in range(2):
        created = eggs.create(
            egg_type="common",
            chat_id=-100 - i,
            spawn_time=_t.time(),
            owner_id=user.id,
            hatch_time=_t.time() + 3600,
            status="incubating",
            claim_time=_t.time(),
        )
        assert created.id
    q = FakeQuery(user, "tr:eggs")
    run(tr.treasury_callback(type("U", (), {"callback_query": q})(), ctx))
    etext2 = q.edits[0][0]
    check("eggs counts real incubating eggs", "🥚 تخم معمولی: ۲" in etext2, etext2)
    check("all egg types are listed",
          all(config.EGG_TYPES[k]["short"] in etext2 for k in config.EGG_TYPES), etext2)

    counts = eggs.count_incubating_by_type(user.id)
    check("egg counts come from the eggs table", counts.get("common") == 2, counts)

    # hatched/expired eggs must not be counted as held
    check("only incubating eggs are counted",
          sum(counts.values()) == len(eggs.list_active_by_owner(user.id)), counts)

    # ---------- back navigation ----------
    q = FakeQuery(user, "tr:home")
    run(tr.treasury_callback(type("U", (), {"callback_query": q})(), ctx))
    htext, hmarkup = q.edits[0]
    check("back returns to the treasury", htext.startswith("🏰 خزانه اژدها"), htext)
    check("back restores the home buttons",
          labels(hmarkup) == ["🥩 غذا", "🥚 تخم‌ها"], labels(hmarkup))
    check("home reflects updated currency", "🪨 ابسیدین: ۱۵۰۰" in htext, htext)
    check("all callbacks use the tr: prefix",
          all(d.startswith("tr:") for d in datas(hmarkup)), datas(hmarkup))

    # ---------- read-only guarantee ----------
    before = (players.get(user.id).obsidian, players.get(user.id).aether,
              players.get(user.id).meat, players.get(user.id).fish,
              len(eggs.list_active_by_owner(user.id)))
    for data in ("tr:home", "tr:food", "tr:eggs"):
        q = FakeQuery(user, data)
        run(tr.treasury_callback(type("U", (), {"callback_query": q})(), ctx))
    after = (players.get(user.id).obsidian, players.get(user.id).aether,
             players.get(user.id).meat, players.get(user.id).fish,
             len(eggs.list_active_by_owner(user.id)))
    check("treasury never modifies player data", before == after, (before, after))

    # ---------- unknown / malformed callbacks ----------
    for bad in ("tr:", "tr:bogus", "tr"):
        q = FakeQuery(user, bad)
        run(tr.treasury_callback(type("U", (), {"callback_query": q})(), ctx))
        check(f"unknown action {bad!r} is ignored safely", q.edits == [], q.edits)
        check(f"unknown action {bad!r} still answers", len(q.answers) == 1)

    # ---------- error handling ----------
    class BrokenService:
        def contents(self, uid):
            raise RuntimeError("db down")

    broken_ctx = type("C", (), {
        "bot_data": {"player_repo": players, "treasury_service": BrokenService()},
    })()
    msg = FakeMessage()
    upd = type("U", (), {"effective_user": user, "effective_message": msg})()
    run(tr.treasury_command(upd, broken_ctx))   # must not raise
    check("command survives a service error", len(msg.replies) == 1, msg.replies)
    check("command shows an error message",
          "خطا" in msg.replies[0][0], msg.replies)

    q = FakeQuery(user, "tr:food")
    run(tr.treasury_callback(type("U", (), {"callback_query": q})(), broken_ctx))
    check("callback survives a service error", q.edits == [])
    check("callback alerts on error", any(a and "خطا" in a for a in q.answers), q.answers)

    # bots are ignored
    bot_user = FakeUser(99, "bot")
    bot_user.is_bot = True
    q = FakeQuery(bot_user, "tr:home")
    run(tr.treasury_callback(type("U", (), {"callback_query": q})(), ctx))
    check("bot presses are ignored", q.edits == [] and q.answers == [])

    # ---------- unknown player ----------
    empty = treasury.contents(999999)
    check("unknown player yields zeros",
          (empty.obsidian, empty.aether, empty.meat, empty.fish) == (0, 0, 0, 0))
    check("unknown player still lists egg types with 0",
          len(empty.eggs) == len(config.EGG_TYPES)
          and all(s.count == 0 for s in empty.eggs))

    # ---------- other systems still work ----------
    chest = ChestService()
    c = chest.spawn_chest(-500)
    res = chest.open_chest(c.id, user.id)
    check("chest system still works", res.success)
    after_chest = treasury.contents(user.id)
    check("treasury reflects chest rewards immediately",
          after_chest.obsidian >= 1500 + res.rewards.get("obsidian", 0) - 1,
          (after_chest.obsidian, res.rewards))

    print()
    passed = sum(RESULTS)
    print(f"{passed}/{len(RESULTS)} checks passed")
    if passed == len(RESULTS):
        print("All treasury tests passed ✅")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
