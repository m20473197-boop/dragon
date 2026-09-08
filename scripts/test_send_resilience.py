"""Scheduled jobs must survive Telegram send failures (Round 18)."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")
DB = os.path.join(tempfile.mkdtemp(), "resilience.db")
os.environ["DRAGON_DB_PATH"] = DB

from telegram.error import BadRequest, Forbidden, TimedOut  # noqa: E402

import config  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from handlers import chests as chests_mod  # noqa: E402
from handlers import jobs as jobs_mod  # noqa: E402

OK = []


def check(name, cond):
    OK.append(bool(cond))
    print(("✅" if cond else "❌"), name)


class FakeMessage:
    message_id = 1234


class FakeBot:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = 0
        self.kwargs = []

    async def send_message(self, **kw):
        self.calls += 1
        self.kwargs.append(kw)
        exc = self.behaviour(self.calls)
        if exc is not None:
            raise exc
        return FakeMessage()

    async def edit_message_reply_markup(self, **kw):
        return None


class FakeContext:
    def __init__(self, bot, bot_data):
        self.bot = bot
        self.bot_data = bot_data


def build_bot_data():
    from game.chests import ChestService
    from game.eggs import EggService
    from models.chat import ChatRepository
    from models.chest import ChestRepository
    from models.dragon import DragonRepository
    from models.egg import EggRepository
    from models.player import PlayerRepository

    players = PlayerRepository()
    eggs = EggRepository()
    dragons = DragonRepository()
    chats = ChatRepository()
    chest_repo = ChestRepository()
    return {
        "player_repo": players,
        "egg_repo": eggs,
        "dragon_repo": dragons,
        "chat_repo": chats,
        "chest_repo": chest_repo,
        "egg_service": EggService(eggs, players, dragons),
        "chest_service": ChestService(chest_repo, players),
    }


async def main():
    init_db()
    run_migrations()
    bd = build_bot_data()
    chats = bd["chat_repo"]
    chats.touch(-100, "Group A")

    # sleeps make the test slow; neutralize them.
    orig_sleep = asyncio.sleep

    async def fast_sleep(_s):
        await orig_sleep(0)

    chests_mod.asyncio.sleep = fast_sleep

    # 1. Always timing out -> returns None, retries, never raises.
    bot = FakeBot(lambda n: TimedOut())
    ctx = FakeContext(bot, bd)
    res = await chests_mod.safe_send_message(ctx, -100, "hi", what="probe")
    check("TimedOut returns None instead of raising", res is None)
    check("TimedOut is retried", bot.calls == chests_mod.SEND_RETRIES)

    # 2. Timeout then success.
    bot = FakeBot(lambda n: TimedOut() if n == 1 else None)
    res = await chests_mod.safe_send_message(FakeContext(bot, bd), -100, "hi")
    check("retry after a timeout succeeds", res is not None and bot.calls == 2)

    # 3. Blocked bot -> no retry, no raise.
    bot = FakeBot(lambda n: Forbidden("bot was blocked by the user"))
    res = await chests_mod.safe_send_message(FakeContext(bot, bd), -100, "hi")
    check("Forbidden handled without retry", res is None and bot.calls == 1)

    # 4. Invalid chat id -> no retry, no raise.
    bot = FakeBot(lambda n: BadRequest("Chat not found"))
    res = await chests_mod.safe_send_message(FakeContext(bot, bd), -999, "hi")
    check("BadRequest handled without retry", res is None and bot.calls == 1)

    # 5. Timeout kwargs are applied.
    bot = FakeBot(lambda n: None)
    await chests_mod.safe_send_message(FakeContext(bot, bd), -100, "hi")
    kw = bot.kwargs[0]
    check(
        "explicit timeouts passed to Telegram",
        kw["read_timeout"] == chests_mod.SEND_READ_TIMEOUT
        and kw["write_timeout"] == chests_mod.SEND_WRITE_TIMEOUT
        and kw["connect_timeout"] == chests_mod.SEND_CONNECT_TIMEOUT
        and kw["pool_timeout"] == chests_mod.SEND_POOL_TIMEOUT,
    )

    # 6. Caller kwargs win / are preserved.
    bot = FakeBot(lambda n: None)
    await chests_mod.safe_send_message(
        FakeContext(bot, bd), -100, "hi", parse_mode="HTML", read_timeout=99.0
    )
    check(
        "caller kwargs preserved",
        bot.kwargs[0]["parse_mode"] == "HTML" and bot.kwargs[0]["read_timeout"] == 99.0,
    )

    # 7. chest_tick survives a permanently timing-out bot.
    old_chance = config.CHEST_CHANCE_PER_CHECK
    config.CHEST_CHANCE_PER_CHECK = 1.0
    jobs_mod.CHEST_CHANCE_PER_CHECK = 1.0
    bot = FakeBot(lambda n: TimedOut())
    ctx = FakeContext(bot, bd)
    try:
        await jobs_mod.chest_tick(ctx)
        ok = True
    except Exception as exc:  # pragma: no cover
        ok = False
        print("   raised:", exc)
    check("chest_tick does not raise on TimedOut", ok)
    check("chest_tick still attempted a send", bot.calls >= 1)

    # 8. spawn_tick survives a permanently timing-out bot.
    jobs_mod.SPAWN_CHANCE_PER_CHECK = 1.0
    bot = FakeBot(lambda n: TimedOut())
    try:
        await jobs_mod.spawn_tick(FakeContext(bot, bd))
        ok = True
    except Exception as exc:  # pragma: no cover
        ok = False
        print("   raised:", exc)
    check("spawn_tick does not raise on TimedOut", ok)

    # 9. hatch_sweep survives too.
    try:
        await jobs_mod.hatch_sweep(FakeContext(FakeBot(lambda n: TimedOut()), bd))
        ok = True
    except Exception as exc:  # pragma: no cover
        ok = False
        print("   raised:", exc)
    check("hatch_sweep does not raise on TimedOut", ok)

    # 10. A successful chest send still stores the message id.
    bd["chest_service"].expire_stale_chests()
    from database.connection import get_db

    with get_db() as conn:
        conn.execute("DELETE FROM chests")
        conn.commit()
    bot = FakeBot(lambda n: None)
    await jobs_mod.chest_tick(FakeContext(bot, bd))
    with get_db() as conn:
        row = conn.execute("SELECT message_id FROM chests ORDER BY id DESC LIMIT 1").fetchone()
    check("successful chest send stores message_id", row is not None and row[0] == 1234)
    config.CHEST_CHANCE_PER_CHECK = old_chance

    print()
    print(f"{sum(OK)}/{len(OK)} checks passed")
    return 0 if all(OK) else 1


if __name__ == "__main__":
    t0 = time.time()
    code = asyncio.run(main())
    print(f"({time.time() - t0:.1f}s)")
    sys.exit(code)
