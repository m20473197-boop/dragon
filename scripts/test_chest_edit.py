"""Chest messages are edited in place, and the «اژدها» command rename."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")
os.environ["DRAGON_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "chestedit.db")

from telegram.error import BadRequest  # noqa: E402

import config  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from handlers import COMMAND_MAP, _setup_shared_objects, text_router  # noqa: E402
from handlers import chests as ch  # noqa: E402
from handlers import dragon_manage as dm  # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append(bool(cond))
    print(("✅" if cond else "❌"), name, extra if not cond else "")


# --- fakes ------------------------------------------------------------------
class Bot:
    def __init__(self):
        self.sent = []
        self.edited = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        class S:
            message_id = 555
        return S()

    async def edit_message_text(self, chat_id=None, message_id=None, text=None, **kw):
        self.edited.append((chat_id, message_id, text))
        return None


class Query:
    def __init__(self, data, uid, fail_edit=False):
        self.data = data
        self.fail_edit = fail_edit
        self.from_user = type(
            "U", (), {
                "id": uid, "is_bot": False, "username": f"u{uid}",
                "full_name": f"User{uid}",
                "mention_html": lambda self, n: n,
            },
        )()
        self.message = type("M", (), {"chat_id": -100})()
        self.toasts = []
        self.edits = []
        self.markup_edits = []

    async def answer(self, text=None, show_alert=False):
        if text:
            self.toasts.append(text)

    async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
        if self.fail_edit:
            raise BadRequest("message to edit not found")
        self.edits.append((text, reply_markup))

    async def edit_message_reply_markup(self, reply_markup=None):
        self.markup_edits.append(reply_markup)


class Upd:
    def __init__(self, q):
        self.callback_query = q
        self.effective_user = q.from_user
        self.effective_chat = type("C", (), {"id": -100, "title": "G", "type": "group"})()
        self.effective_message = None


class Msg:
    def __init__(self, text):
        self.text = text
        self.replies = []
        self.chat = type("C", (), {"id": -100})()

    async def reply_text(self, t, reply_markup=None, **k):
        self.replies.append((t, reply_markup))
        class S:
            message_id = 1
        return S()


class TxtUpd:
    def __init__(self, text, uid):
        self.effective_message = Msg(text)
        self.message = self.effective_message
        self.effective_user = type(
            "U", (), {"id": uid, "is_bot": False, "username": "u"}
        )()
        self.effective_chat = type("C", (), {"id": -100, "title": "G", "type": "group"})()
        self.callback_query = None


class Ctx:
    def __init__(self, bot_data, bot):
        self.bot_data = bot_data
        self.bot = bot
        self.user_data = {}
        self.chat_data = {}
        self.job_queue = None


def main():
    init_db()
    run_migrations()
    app = type("A", (), {"bot_data": {}})()
    _setup_shared_objects(app)
    bot = Bot()
    ctx = Ctx(app.bot_data, bot)

    # =====================================================================
    # PART 1 — the command rename
    # =====================================================================
    check("command constant is now «اژدها»", config.COMMAND_MY_DRAGONS_MENU == "اژدها")
    check("«اژدها» is routed", "اژدها" in COMMAND_MAP)
    check("old «اژدها های من» handler removed", "اژدها های من" not in COMMAND_MAP)
    check("old «اژدهاهای من» alias removed", "اژدهاهای من" not in COMMAND_MAP)
    check("«اژدها» opens the dragon selection system",
          COMMAND_MAP["اژدها"] is dm.my_dragons_menu_command)
    check("no stale command words remain",
          not any("های من" in k for k in COMMAND_MAP), list(COMMAND_MAP))

    players = app.bot_data["player_repo"]
    dragons = app.bot_data["dragon_repo"]
    UID = 321
    players.get_or_create(UID, "tester")
    made = [
        dragons.create(
            owner_id=UID, dragon_type=t, from_egg_id=None, name=n, level=1, xp=0,
            hp=100, max_hp=100, power=20, hunger=100, last_fed_time=None,
        )
        for n, t in (("آذر", "fire"), ("یخ پنجه", "ice"), ("رعد", "shadow"))
    ]

    u = TxtUpd("اژدها", UID)
    asyncio.run(text_router(u, ctx))
    check("«اژدها» replies", len(u.effective_message.replies) == 1)
    text, markup = u.effective_message.replies[0]
    check("title is the required one", text == "🐉 انتخاب اژدها:", text)
    labels = [b.text for row in markup.inline_keyboard for b in row]
    check("one button per dragon", len(labels) == 3, labels)
    check("buttons show emoji + name",
          all(any(d.name in lbl for lbl in labels) for d in made), labels)
    datas = [b.callback_data for row in markup.inline_keyboard for b in row]
    check("buttons still use the dg:view selection logic",
          all(d.startswith("dg:view:") for d in datas), datas)

    # the old command must now do nothing (falls through to the name capture)
    old = TxtUpd("اژدها های من", UID)
    asyncio.run(text_router(old, ctx))
    check("old command no longer opens the menu",
          not any("انتخاب اژدها" in t for t, _ in old.effective_message.replies),
          old.effective_message.replies)

    # selection / active-dragon systems untouched
    q = Query(f"dg:view:{made[0].id}", UID)
    asyncio.run(dm.dragon_manage_callback(Upd(q), ctx))
    check("selecting a dragon still opens its profile",
          q.edits and "آذر" in q.edits[0][0])
    check("selecting still does NOT change the active dragon",
          players.get_active_dragon_id(UID) is None)
    q = Query(f"dg:setactive:{made[0].id}", UID)
    asyncio.run(dm.dragon_manage_callback(Upd(q), ctx))
    check("set-active button still works",
          players.get_active_dragon_id(UID) == made[0].id)

    # =====================================================================
    # PART 2 — chest message editing
    # =====================================================================
    chest_service = app.bot_data["chest_service"]
    chest_repo = app.bot_data["chest_repo"]

    # reward formatting
    rewards = {"obsidian": 850, "aether": 3, "meat": 10, "fish": 15}
    body = ch.format_rewards(rewards, opener="Ali")
    check("opened text has the title", body.startswith("🎁 صندوق باز شد!"), body)
    check("opened text names the opener", "👤 Ali" in body, body)
    for token in ("🪨 +۸۵۰", "✨ +۳", "🥩 +۱۰", "🐟 +۱۵"):
        check(f"rewards list contains {token}", token in body, body)
    check("formatter still works without an opener (back-compat)",
          "👤" not in ch.format_rewards(rewards))

    # spawn a chest and store its message id, exactly like the job does
    OPENER = 777
    players.get_or_create(OPENER, "opener")
    chest = chest_service.spawn_chest(-100)
    chest_repo.set_message_id(chest.id, 4242)
    check("chest message_id is saved at spawn",
          chest_repo.get(chest.id).message_id == 4242)

    before_sent = len(bot.sent)
    q = Query(f"open_chest:{chest.id}", OPENER)
    asyncio.run(ch.open_chest_callback(Upd(q), ctx))

    check("the chest message was edited", len(q.edits) == 1, q.edits)
    check("NO new message was sent", len(bot.sent) == before_sent, bot.sent)
    edited_text, edited_markup = q.edits[0]
    check("edited text is the opened-chest message",
          edited_text.startswith("🎁 صندوق باز شد!"), edited_text)
    check("edited text names the opener", "User777" in edited_text, edited_text)
    check("the button was removed", edited_markup is None)
    check("the opener got a toast", any("مال تو" in t for t in q.toasts), q.toasts)
    check("rewards were credited",
          players.get(OPENER).obsidian > 0, players.get(OPENER).obsidian)
    check("database logic unchanged: chest marked opened",
          chest_repo.get(chest.id).status == "opened")
    check("database logic unchanged: opener recorded",
          chest_repo.get(chest.id).opened_by == OPENER)
    check("reward snapshot still stored",
          chest_repo.get(chest.id).reward_dict().get("obsidian") ==
          players.get(OPENER).obsidian)

    # a second user cannot open it
    SECOND = 888
    players.get_or_create(SECOND, "second")
    obs_before = players.get(SECOND).obsidian
    q2 = Query(f"open_chest:{chest.id}", SECOND)
    asyncio.run(ch.open_chest_callback(Upd(q2), ctx))
    check("second user is refused",
          any("زودتر" in t for t in q2.toasts), q2.toasts)
    check("second user gets no rewards", players.get(SECOND).obsidian == obs_before)
    check("second user's press sends no message", len(bot.sent) == before_sent)
    check("second user's press does not rewrite the result", len(q2.edits) == 0)
    check("opener is unchanged", chest_repo.get(chest.id).opened_by == OPENER)

    # fallback path: the query edit fails, the stored message_id is used
    chest2 = chest_service.spawn_chest(-101)
    chest_repo.set_message_id(chest2.id, 9001)
    before_sent = len(bot.sent)
    q3 = Query(f"open_chest:{chest2.id}", OPENER, fail_edit=True)
    asyncio.run(ch.open_chest_callback(Upd(q3), ctx))
    check("fallback edits via the stored message_id",
          bot.edited and bot.edited[-1][1] == 9001, bot.edited)
    check("fallback targets the chest's own group",
          bot.edited[-1][0] == -101, bot.edited[-1])
    check("fallback still sends no new message", len(bot.sent) == before_sent)
    check("rewards still granted when the edit path degrades",
          chest_repo.get(chest2.id).status == "opened")

    # a chest that no longer exists
    q4 = Query("open_chest:999999", OPENER)
    asyncio.run(ch.open_chest_callback(Upd(q4), ctx))
    check("unknown chest is handled gracefully",
          any("پیدا نشد" in t for t in q4.toasts), q4.toasts)
    check("unknown chest clears the buttons", q4.markup_edits == [None])

    # malformed callback data must not raise
    q5 = Query("open_chest:abc", OPENER)
    asyncio.run(ch.open_chest_callback(Upd(q5), ctx))
    check("malformed callback data is ignored", q5.edits == [])

    print()
    passed = sum(RESULTS)
    print(f"{passed}/{len(RESULTS)} checks passed")
    if passed == len(RESULTS):
        print("All chest-edit / command-rename tests passed ✅")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
