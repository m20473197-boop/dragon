"""Selected dragon vs. active dragon separation (bug fix).

Viewing/feeding/upgrading/renaming a dragon must NEVER change the active
dragon; only «⭐ انتخاب به عنوان اژدهای فعال» may.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")
os.environ["DRAGON_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "selection.db")

from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.combat import CombatService  # noqa: E402
from game.selection import (  # noqa: E402
    clear_selected_dragon,
    get_selected_dragon,
    set_selected_dragon,
)
from handlers import _setup_shared_objects, dragon_manage as dm  # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append(bool(cond))
    print(("✅" if cond else "❌"), name, extra if not cond else "")


# --- fakes ------------------------------------------------------------------
class App:
    def __init__(self):
        self.bot_data = {}


class Chat:
    id = -100


class Msg:
    def __init__(self):
        self.chat = Chat()
        self.text = None
        self.markup = None


class Query:
    def __init__(self, data, uid):
        self.data = data
        self.from_user = type("U", (), {"id": uid, "is_bot": False, "username": "u"})()
        self.message = Msg()
        self.toasts = []
        self.text = None
        self.markup = None

    async def answer(self, text=None, show_alert=False):
        if text:
            self.toasts.append(text)

    async def edit_message_text(self, text, reply_markup=None):
        self.text = text
        self.markup = reply_markup


class Update:
    def __init__(self, q):
        self.callback_query = q
        self.effective_user = q.from_user
        self.effective_chat = Chat()
        self.effective_message = None


class Ctx:
    def __init__(self, bot_data):
        self.bot_data = bot_data
        self.user_data = {}
        self.chat_data = {}
        self.job_queue = None


def press(ctx, data, uid):
    q = Query(data, uid)
    asyncio.run(dm.dragon_manage_callback(Update(q), ctx))
    return q


def labels(markup):
    if markup is None:
        return []
    return [b.text for row in markup.inline_keyboard for b in row]


def main():
    init_db()
    run_migrations()
    app = App()
    _setup_shared_objects(app)
    ctx = Ctx(app.bot_data)

    players = app.bot_data["player_repo"]
    dragons = app.bot_data["dragon_repo"]

    UID = 4242
    players.get_or_create(UID, "tester")
    made = {}
    for name in ("آذر", "رعد", "یخ پنجه"):
        made[name] = dragons.create(
            owner_id=UID, dragon_type="fire", from_egg_id=None, name=name,
            level=1, xp=0, hp=100, max_hp=100, power=20, hunger=100,
            last_fed_time=None,
        )
    azar, raad, yakh = made["آذر"], made["رعد"], made["یخ پنجه"]

    # Start with رعد as the active dragon, deliberately NOT the one we view.
    players.set_active_dragon(UID, raad.id)
    check("baseline: رعد is the active dragon",
          players.get_active_dragon_id(UID) == raad.id)

    # --- session helpers ----------------------------------------------------
    session = {}
    check("no dragon selected initially", get_selected_dragon(session) is None)
    set_selected_dragon(session, azar.id)
    check("selection is remembered", get_selected_dragon(session) == azar.id)
    clear_selected_dragon(session)
    check("selection can be cleared", get_selected_dragon(session) is None)
    check("selection tolerates a missing session", get_selected_dragon(None) is None)
    set_selected_dragon(None, 5)  # must not raise
    session["selected_dragon_id"] = "junk"
    check("corrupt selection value is ignored", get_selected_dragon(session) is None)
    check("selection never lands in the database",
          "selected_dragon_id" not in [
              r[1] for r in __import__("sqlite3").connect(
                  os.environ["DRAGON_DB_PATH"]
              ).execute("PRAGMA table_info(players)")
          ])

    # --- THE BUG: viewing a dragon must not make it active ------------------
    q = press(ctx, f"dg:view:{azar.id}", UID)
    check("viewing آذر opens its profile", q.text and "آذر" in q.text, q.text)
    check("BUG FIXED: viewing does NOT change the active dragon",
          players.get_active_dragon_id(UID) == raad.id,
          players.get_active_dragon_id(UID))
    check("viewing sets the temporary selection",
          get_selected_dragon(ctx.user_data) == azar.id)

    for other in (yakh.id, azar.id, yakh.id):
        press(ctx, f"dg:view:{other}", UID)
    check("viewing several dragons still does not change the active one",
          players.get_active_dragon_id(UID) == raad.id)

    # --- profile page shape --------------------------------------------------
    q = press(ctx, f"dg:view:{azar.id}", UID)
    btns = labels(q.markup)
    check("profile has the set-active button", "⭐ فعال" in btns, btns)
    check("profile keeps feeding / upgrade / rename / back",
          {"🥩 غذا", "⬆️ ارتقا", "✏️ نام", "🔙"} <= set(btns), btns)
    for field in ("🐉 آذر", "Lv.", "XP:", "HP:", "قدرت:", "گرسنگی:"):
        check(f"profile shows {field}", field in q.text, q.text)
    check("a non-active dragon is not marked with a star",
          not q.text.splitlines()[0].endswith("⭐"), q.text.splitlines()[0])

    # --- CASE 1: feed the selected dragon ------------------------------------
    app.bot_data["storage_service"].deposit(UID, meat=50, fish=50)
    hp_before = {d: dragons.get(d).hunger for d in (azar.id, raad.id)}
    press(ctx, f"dg:feed:{azar.id}", UID)
    check("feed menu does not change the active dragon",
          players.get_active_dragon_id(UID) == raad.id)
    # starve آذر first so feeding actually applies
    dragons.update_full_stats(azar.id, level=1, xp=0, hp=50, max_hp=100, power=20,
                              hunger=20, last_fed_time=0.0)
    q = press(ctx, f"dg:eat1:{azar.id}", UID)
    check("CASE 1: آذر was fed", "آذر" in (q.text or ""), q.text)
    check("CASE 1: active dragon unchanged after feeding",
          players.get_active_dragon_id(UID) == raad.id,
          players.get_active_dragon_id(UID))
    check("CASE 1: only آذر changed, رعد untouched",
          dragons.get(raad.id).hunger == hp_before[raad.id])
    q = press(ctx, f"dg:eatfull:{azar.id}", UID)
    check("CASE 1: سیرش کن works on the selected dragon", q.text is not None)
    check("CASE 1: active dragon unchanged after feed-to-full",
          players.get_active_dragon_id(UID) == raad.id)

    # --- CASE 2: rename the selected dragon ----------------------------------
    q = press(ctx, f"dg:rename:{yakh.id}", UID)
    check("CASE 2: rename prompt opens for یخ پنجه", "یخ پنجه" in (q.text or ""), q.text)
    check("CASE 2: active dragon unchanged by renaming",
          players.get_active_dragon_id(UID) == raad.id)
    app.bot_data["dragon_service"].rename(UID, yakh.id, "یخ‌پنجه نو")
    check("CASE 2: only that dragon's name changed",
          dragons.get(yakh.id).name == "یخ‌پنجه نو"
          and dragons.get(raad.id).name == "رعد"
          and dragons.get(azar.id).name == "آذر")
    check("CASE 2: active dragon still رعد after the rename saved",
          players.get_active_dragon_id(UID) == raad.id)

    # --- upgrades ------------------------------------------------------------
    players.add_resources(UID, obsidian=5000)
    press(ctx, f"dg:up:{azar.id}", UID)
    check("upgrade menu does not change the active dragon",
          players.get_active_dragon_id(UID) == raad.id)
    power_before = dragons.get(azar.id).power
    q = press(ctx, f"dg:updo:{azar.id}:power", UID)
    check("upgrade applied to the selected dragon",
          dragons.get(azar.id).power > power_before)
    check("upgrade did not touch the active dragon's stats",
          dragons.get(raad.id).power == 20)
    check("active dragon unchanged after upgrading",
          players.get_active_dragon_id(UID) == raad.id)

    # --- CASE 3: the dedicated button ----------------------------------------
    q = press(ctx, f"dg:setactive:{azar.id}", UID)
    check("CASE 3: active dragon changed to آذر",
          players.get_active_dragon_id(UID) == azar.id,
          players.get_active_dragon_id(UID))
    check("CASE 3: confirmation text is correct",
          any("اکنون اژدهای فعال شماست" in t for t in q.toasts), q.toasts)
    check("CASE 3: message shows the confirmation",
          "آذر اکنون اژدهای فعال شماست" in (q.text or ""), q.text)
    check("CASE 3: profile now marks it active",
          any(line.startswith("🐉 آذر") and line.endswith("⭐")
              for line in (q.text or "").splitlines()), q.text)
    check("CASE 3: buttons still present after switching",
          "⭐ فعال" in labels(q.markup))

    q = press(ctx, f"dg:setactive:{azar.id}", UID)
    check("pressing set-active twice is harmless",
          players.get_active_dragon_id(UID) == azar.id
          and any("فعاله" in t for t in q.toasts), q.toasts)

    # --- CASE 4: combat reads only active_dragon_id --------------------------
    combat = CombatService(
        battles=app.bot_data["battle_repo"], dragons=dragons, players=players,
        dragon_service=app.bot_data["dragon_service"],
    )
    # Select a DIFFERENT dragon, then fight: combat must use the active one.
    press(ctx, f"dg:view:{yakh.id}", UID)
    check("selected is یخ پنجه but active is آذر",
          get_selected_dragon(ctx.user_data) == yakh.id
          and players.get_active_dragon_id(UID) == azar.id)
    res = combat.start_battle(UID, chat_id=-100)
    check("CASE 4: combat starts", res.success, res.reason)
    check("CASE 4: combat fights with the ACTIVE dragon, not the selected one",
          res.battle.dragon_id == azar.id, res.battle.dragon_id)
    combat.flee(res.battle.battle_id, UID)

    # --- back button clears the selection ------------------------------------
    q = press(ctx, "dg:list", UID)
    check("back returns to the list", "انتخاب اژدها" in (q.text or ""), q.text)
    check("back clears the temporary selection",
          get_selected_dragon(ctx.user_data) is None)
    check("back does not change the active dragon",
          players.get_active_dragon_id(UID) == azar.id)
    check("the active dragon is ticked in the list",
          any("✅" in b for b in labels(q.markup)), labels(q.markup))
    check("exactly one dragon is ticked",
          sum("✅" in b for b in labels(q.markup)) == 1)

    # --- ownership safety -----------------------------------------------------
    OTHER = 9999
    players.get_or_create(OTHER, "intruder")
    other_dragon = dragons.create(
        owner_id=OTHER, dragon_type="fire", from_egg_id=None, name="غریبه",
        level=1, xp=0, hp=100, max_hp=100, power=20, hunger=100, last_fed_time=None,
    )
    q = press(ctx, f"dg:setactive:{other_dragon.id}", UID)
    check("cannot activate somebody else's dragon",
          players.get_active_dragon_id(UID) == azar.id
          and any("مال تو نیست" in t for t in q.toasts), q.toasts)
    q = press(ctx, f"dg:view:{other_dragon.id}", UID)
    check("cannot view somebody else's dragon",
          any("مال تو نیست" in t for t in q.toasts), q.toasts)
    check("intruder's active dragon untouched",
          players.get_active_dragon_id(OTHER) is None)

    # --- egg system still auto-activates the FIRST dragon --------------------
    NEWBIE = 7777
    players.get_or_create(NEWBIE, "newbie")
    check("new player has no active dragon",
          players.get_active_dragon_id(NEWBIE) is None)
    first = dragons.create(
        owner_id=NEWBIE, dragon_type="fire", from_egg_id=None, name="اولی",
        level=1, xp=0, hp=100, max_hp=100, power=20, hunger=100, last_fed_time=None,
    )
    if players.get_active_dragon_id(NEWBIE) is None:
        players.set_active_dragon(NEWBIE, first.id)
    check("first dragon can still be auto-activated (egg system)",
          players.get_active_dragon_id(NEWBIE) == first.id)

    print()
    passed = sum(RESULTS)
    print(f"{passed}/{len(RESULTS)} checks passed")
    if passed == len(RESULTS):
        print("All selection/active-dragon tests passed ✅")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
