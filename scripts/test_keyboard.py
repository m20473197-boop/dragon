"""Main reply keyboard tests (UI only).

The keyboard is an accessibility layer: every button sends the text of an
existing Persian command. These tests assert that

  * the menu shows exactly the five requested buttons,
  * each button routes to the same handler as the typed command,
  * every existing Persian command still works unchanged,
  * خزانه is NOT on the menu but is still typable,
  * slash commands are untouched,
  * spacing / semi-space variants all resolve.

Run: python3 scripts/test_keyboard.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_keyboard_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")
os.environ.setdefault("DRAGON_ADMIN_IDS", "1")

import config  # noqa: E402
import handlers  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from handlers.keyboards import (  # noqa: E402
    MENU_BUTTONS,
    main_menu_keyboard,
    resolve_menu_button,
)

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


class FakeMessage:
    def __init__(self, text):
        self.text = text
        self.chat = type("C", (), {"id": -1, "type": "group", "title": "g"})()
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return None


class FakeUpdate:
    def __init__(self, text, user_id=1):
        self.effective_message = FakeMessage(text)
        self.message = self.effective_message
        self.effective_user = type(
            "U", (), {"id": user_id, "username": "tester", "is_bot": False}
        )()
        self.effective_chat = self.effective_message.chat


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def main() -> None:
    loop_ctx = type("C", (), {
        "bot_data": {}, "user_data": {}, "chat_data": {}, "job_queue": None,
    })()

    # Swap every command handler for a recorder so we can see which one a
    # given message reaches. The real handlers are restored afterwards.
    original = dict(handlers.COMMAND_MAP)
    seen: list[str] = []

    def recorder(name):
        async def _handler(update, context):
            seen.append(name)
        return _handler

    for key in list(handlers.COMMAND_MAP):
        handlers.COMMAND_MAP[key] = recorder(key)

    def route(text):
        seen.clear()
        run(handlers.text_router(FakeUpdate(text), loop_ctx))
        return seen[0] if seen else None

    print("\n1. The menu has exactly the requested buttons")
    keyboard = main_menu_keyboard()
    captions = [b.text for row in keyboard.keyboard for b in row]
    check("five buttons", len(captions) == 5, captions)
    for expected in ("🥚 تخم‌ها", "🐉 اژدها", "❄️ سردخانه", "🏪 بازار", "🧬 پیوند"):
        check(f"menu has {expected}", expected in captions, captions)
    check("keyboard resizes", keyboard.resize_keyboard is True)
    check("keyboard is persistent", keyboard.is_persistent is True)

    print("2. خزانه is not on the main menu")
    check("خزانه absent from the menu",
          not any("خزانه" in c for c in captions), captions)

    print("3. Each button runs the existing command handler")
    for caption, command in MENU_BUTTONS:
        check(f"[{caption}] -> «{command}»", route(caption) == command,
              route(caption))
        check(f"[{caption}] maps to a real command",
              command in original, command)

    print("4. Every existing Persian command still works")
    for command in original:
        check(f"typed «{command}» still routes", route(command) == command,
              route(command))
    check("no command was removed",
          set(handlers.COMMAND_MAP) == set(original))
    check("خزانه is still typable",
          route(config.COMMAND_TREASURY) == config.COMMAND_TREASURY)

    print("5. Spacing and semi-space variants resolve")
    for variant in ("تخم ها", "تخم\u200cها", "🥚 تخم\u200cها", "🥚 تخم ها",
                    "  تخم   ها  "):
        check(f"{variant!r} -> «{config.COMMAND_EGGS}»",
              route(variant) == config.COMMAND_EGGS, route(variant))

    print("6. Unrelated text is not captured by the menu")
    check("plain chatter is not a command", route("سلام دوستان") is None)
    check("resolve_menu_button ignores non-buttons",
          resolve_menu_button("سلام دوستان") is None)
    check("resolve_menu_button ignores a bare command",
          resolve_menu_button(config.COMMAND_EGGS) is None
          or resolve_menu_button(config.COMMAND_EGGS) == config.COMMAND_EGGS)

    # Restore the real handlers before touching the application.
    handlers.COMMAND_MAP.clear()
    handlers.COMMAND_MAP.update(original)

    print("7. Slash commands are unchanged")
    from telegram.ext import Application, CommandHandler
    app = Application.builder().token("1:A").build()
    handlers.register_all(app)
    slash = sorted(
        c for group in app.handlers.values() for h in group
        if isinstance(h, CommandHandler) for c in h.commands
    )
    check("slash commands intact",
          slash == ["arena", "breeding", "help", "start"], slash)

    print("8. /start and /help deliver the keyboard")
    from handlers.common import help_command, start_command
    for name, handler in (("start", start_command), ("help", help_command)):
        update = FakeUpdate("/" + name)
        run(handler(update, loop_ctx))
        _text, kwargs = update.effective_message.replies[0]
        markup = kwargs.get("reply_markup")
        check(f"/{name} attaches the menu", markup is not None)
        if markup is not None:
            sent = [b.text for row in markup.keyboard for b in row]
            check(f"/{name} sends all five buttons", len(sent) == 5, sent)

    print()
    total = PASSED + FAILED
    if FAILED:
        print(f"❌ {FAILED} of {total} checks failed")
        sys.exit(1)
    print(f"All keyboard tests passed ✅  ({PASSED}/{total} checks)")


if __name__ == "__main__":
    main()
