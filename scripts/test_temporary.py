"""Version 5: temporary eggs/chests, edit-in-place claiming and cleanup.

Covers:
  1. egg spawn sends ONE message with one button
  2. collecting edits that message in place (no new message, button removed)
  3. a second user cannot collect the same egg
  4. a second user cannot open the same chest
  5. unopened chests expire, are removed from play and their message deleted
  6. uncollected eggs expire, are removed from play and their message deleted
  7. claimed/opened messages are deleted after MESSAGE_DELETE_TIME
  8. deadlines are stored in the DB, so timers survive a restart
  9. groups stay independent
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")
os.environ["DRAGON_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "temp.db")

import config  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.chests import ChestService  # noqa: E402
from game.eggs import EggService  # noqa: E402
from handlers import chests as chest_h  # noqa: E402
from handlers import cleanup as cl  # noqa: E402
from handlers import jobs  # noqa: E402
from handlers import spawn as spawn_h  # noqa: E402
from models.chest import ChestRepository  # noqa: E402
from models.egg import EggRepository  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append(bool(cond))
    print(("✅" if cond else "❌"), name, ("→ " + str(extra)) if not cond else "")


# --- fakes ------------------------------------------------------------------
class FakeBot:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.deleted = []
        self.markup_edits = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        mid = 1000 + len(self.sent)
        return type("M", (), {"message_id": mid, "chat_id": chat_id})()

    async def edit_message_text(self, chat_id=None, message_id=None, text=None, **kw):
        self.edited.append((chat_id, message_id, text))

    async def edit_message_reply_markup(self, chat_id=None, message_id=None, **kw):
        self.markup_edits.append((chat_id, message_id))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeQuery:
    def __init__(self, user, data, message_id=None, chat_id=None, bot=None):
        self.from_user = user
        self.data = data
        self.answers = []
        self.edits = []
        self.bot = bot
        self.message = type("M", (), {"message_id": message_id, "chat_id": chat_id})()

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text, **kw):
        self.edits.append(text)
        if self.bot is not None:
            self.bot.edited.append((self.message.chat_id, self.message.message_id, text))

    async def edit_message_reply_markup(self, reply_markup=None):
        if self.bot is not None:
            self.bot.markup_edits.append((self.message.chat_id, self.message.message_id))


class FakeUser:
    def __init__(self, uid, name):
        self.id = uid
        self.username = name
        self.full_name = name
        self.is_bot = False

    def mention_html(self, label):
        return f"<a href='tg://user?id={self.id}'>{label}</a>"


class Ctx:
    def __init__(self, bot, data):
        self.bot = bot
        self.bot_data = data
        self.job_queue = None


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def main():
    init_db()
    run_migrations()

    eggs, chests, players = EggRepository(), ChestRepository(), PlayerRepository()
    egg_service = EggService()
    chest_service = ChestService()
    bot = FakeBot()
    ctx = Ctx(bot, {
        "egg_service": egg_service,
        "chest_service": chest_service,
        "player_repo": players,
        "chat_repo": None,
    })

    # ---------- config ----------
    # These are deliberately configurable (env overrides), so assert they are
    # sane and actually applied rather than pinning one specific number.
    check("CHEST_EXPIRE_TIME is a positive number of seconds",
          isinstance(config.CHEST_EXPIRE_TIME, int) and config.CHEST_EXPIRE_TIME > 0,
          config.CHEST_EXPIRE_TIME)
    check("EGG_EXPIRE_TIME is a positive number of seconds",
          isinstance(config.EGG_EXPIRE_TIME, int) and config.EGG_EXPIRE_TIME > 0,
          config.EGG_EXPIRE_TIME)
    check("MESSAGE_DELETE_TIME is a positive number of seconds",
          isinstance(config.MESSAGE_DELETE_TIME, int) and config.MESSAGE_DELETE_TIME > 0,
          config.MESSAGE_DELETE_TIME)
    check("chest open window follows CHEST_EXPIRE_TIME",
          config.CHEST_OPEN_WINDOW_SECONDS == config.CHEST_EXPIRE_TIME)
    check("egg claim window follows EGG_EXPIRE_TIME",
          config.CLAIM_WINDOW_SECONDS == config.EGG_EXPIRE_TIME)

    # ---------- 1. egg spawn message ----------
    check("egg spawn text matches the spec",
          spawn_h.SPAWN_TEXT == "🥚 یک تخم اژدها پیدا شد!", spawn_h.SPAWN_TEXT)
    kb = spawn_h.build_spawn_keyboard(1).inline_keyboard
    check("egg spawn has exactly one button", len(kb) == 1 and len(kb[0]) == 1)
    check("egg button label matches the spec",
          kb[0][0].text == "🥚 نگهداری از تخم", kb[0][0].text)

    # ---------- 2. collecting edits in place ----------
    egg = egg_service.spawn_wild_egg(-100)
    eggs.set_message_id(egg.id, 555)
    egg = eggs.get(egg.id)
    ali = FakeUser(1, "Ali")
    before_sent = len(bot.sent)
    q = FakeQuery(ali, f"claim_egg:{egg.id}", message_id=555, chat_id=-100, bot=bot)
    run(spawn_h.claim_callback(type("U", (), {"callback_query": q})(), ctx))

    check("collecting sends NO new message", len(bot.sent) == before_sent, bot.sent)
    check("collecting edits the original message", len(q.edits) == 1, q.edits)
    edited = q.edits[0] if q.edits else ""
    check("edited text has the collected title",
          edited.startswith("🥚 تخم برداشته شد!"), edited)
    check("edited text names the player",
          "👤 بازیکن:" in edited and "Ali" in edited, edited)
    check("edited message is short", len([l for l in edited.split("\n") if l.strip()]) == 2, edited)

    stored = eggs.get(egg.id)
    check("egg is now owned", stored.owner_id == ali.id)
    check("egg left the available pool", stored.status == "incubating", stored.status)

    # ---------- 7/8. deletion deadline persisted ----------
    check("claimed egg has a stored deletion deadline", stored.delete_after is not None)
    if stored.delete_after:
        delta = stored.delete_after - time.time()
        # The scheduled deadline must honour the configured value, whatever
        # it is set to (production 300s, fast testing e.g. 20s).
        tolerance = max(5, config.MESSAGE_DELETE_TIME * 0.1)
        check("egg deadline honours MESSAGE_DELETE_TIME",
              abs(delta - config.MESSAGE_DELETE_TIME) <= tolerance,
              f"delta={delta} expected~{config.MESSAGE_DELETE_TIME}")

    # ---------- 3. second user cannot collect ----------
    sara = FakeUser(2, "Sara")
    q2 = FakeQuery(sara, f"claim_egg:{egg.id}", message_id=555, chat_id=-100, bot=bot)
    run(spawn_h.claim_callback(type("U", (), {"callback_query": q2})(), ctx))
    check("second collector is refused", q2.edits == [], q2.edits)
    check("second collector gets an alert",
          any(a and "زودتر" in a for a in q2.answers), q2.answers)
    check("egg owner unchanged after second press", eggs.get(egg.id).owner_id == ali.id)

    # ---------- 4. second user cannot open a chest ----------
    chest = chest_service.spawn_chest(-100)
    chests.set_message_id(chest.id, 777)
    q3 = FakeQuery(ali, f"open_chest:{chest.id}", message_id=777, chat_id=-100, bot=bot)
    run(chest_h.open_chest_callback(type("U", (), {"callback_query": q3})(), ctx))
    check("chest opener sees the reward card",
          q3.edits and q3.edits[0].startswith("🎁 صندوق باز شد!"), q3.edits)
    opened = chests.get(chest.id)
    check("chest is marked opened", opened.status == "opened", opened.status)
    check("opened chest has a deletion deadline", opened.delete_after is not None)

    q4 = FakeQuery(sara, f"open_chest:{chest.id}", message_id=777, chat_id=-100, bot=bot)
    run(chest_h.open_chest_callback(type("U", (), {"callback_query": q4})(), ctx))
    check("second opener is refused", q4.edits == [], q4.edits)
    check("chest opener unchanged", chests.get(chest.id).opened_by == ali.id)

    # ---------- 7. cleanup deletes the result messages ----------
    bot.deleted.clear()
    eggs.set_delete_after(egg.id, time.time() - 1)
    chests.set_delete_after(chest.id, time.time() - 1)
    run(cl.cleanup_tick(ctx))
    check("claimed egg message deleted", (-100, 555) in bot.deleted, bot.deleted)
    check("opened chest message deleted", (-100, 777) in bot.deleted, bot.deleted)
    check("egg message_id cleared", eggs.get(egg.id).message_id is None)
    check("egg deadline cleared", eggs.get(egg.id).delete_after is None)
    check("chest deadline cleared", chests.get(chest.id).delete_after is None)

    # cleanup must not re-delete on the next tick
    bot.deleted.clear()
    run(cl.cleanup_tick(ctx))
    check("cleanup does not repeat itself", bot.deleted == [], bot.deleted)

    # ---------- 8. deadlines survive a restart ----------
    egg2 = egg_service.spawn_wild_egg(-200)
    eggs.set_message_id(egg2.id, 888)
    eggs.set_delete_after(egg2.id, time.time() - 5)
    fresh_service = EggService()          # brand-new objects, as after a reboot
    fresh_ctx = Ctx(bot, {"egg_service": fresh_service,
                          "chest_service": ChestService(),
                          "player_repo": PlayerRepository()})
    bot.deleted.clear()
    run(cl.cleanup_tick(fresh_ctx))
    check("deadline from before a restart is honoured",
          (-200, 888) in bot.deleted, bot.deleted)

    # ---------- 5. unopened chests expire and are deleted ----------
    old_chest = chest_service.spawn_chest(-300, now=time.time() - config.CHEST_EXPIRE_TIME - 10)
    chests.set_message_id(old_chest.id, 999)
    bot.deleted.clear()
    ctx.bot_data["chat_repo"] = type("R", (), {"active_chats": staticmethod(lambda w: [])})()
    run(jobs.chest_tick(ctx))
    check("expired chest message deleted", (-300, 999) in bot.deleted, bot.deleted)
    check("expired chest removed from play",
          chests.get(old_chest.id).status == "expired", chests.get(old_chest.id).status)
    dead = chests.get(old_chest.id)
    check("expired chest cannot be opened",
          chest_service.open_chest(old_chest.id, 3).success is False)
    check("expired chest message_id cleared", dead.message_id is None)

    # ---------- 6. uncollected eggs expire and are deleted ----------
    old_egg = egg_service.spawn_wild_egg(-400, now=time.time() - config.EGG_EXPIRE_TIME - 10)
    eggs.set_message_id(old_egg.id, 1111)
    bot.deleted.clear()
    run(jobs.hatch_sweep(ctx))
    check("expired egg message deleted", (-400, 1111) in bot.deleted, bot.deleted)
    check("expired egg removed from play",
          eggs.get(old_egg.id).status == "expired", eggs.get(old_egg.id).status)
    claimed, _ = egg_service.claim_egg(old_egg.id, 3)
    check("expired egg cannot be collected", claimed is None)

    # ---------- 9. groups are independent ----------
    e_a = egg_service.spawn_wild_egg(-501)
    e_b = egg_service.spawn_wild_egg(-502)
    eggs.set_message_id(e_a.id, 21)
    eggs.set_message_id(e_b.id, 22)
    eggs.set_delete_after(e_a.id, time.time() - 1)     # only group A is due
    bot.deleted.clear()
    run(cl.cleanup_tick(ctx))
    check("only the due group's message is deleted",
          bot.deleted == [(-501, 21)], bot.deleted)
    check("the other group's egg is untouched",
          eggs.get(e_b.id).message_id == 22 and eggs.get(e_b.id).status == "available")

    # ---------- robustness ----------
    bot.deleted.clear()
    orig = bot.delete_message

    async def boom(chat_id, message_id):
        raise RuntimeError("telegram down")

    bot.delete_message = boom
    eggs.set_delete_after(e_b.id, time.time() - 1)
    run(cl.cleanup_tick(ctx))            # must not raise
    check("cleanup survives a delete failure", True)
    check("failed deletion still clears the deadline",
          eggs.get(e_b.id).delete_after is None)
    bot.delete_message = orig

    print()
    passed = sum(RESULTS)
    print(f"{passed}/{len(RESULTS)} checks passed")
    if passed == len(RESULTS):
        print("All temporary-message tests passed ✅")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
