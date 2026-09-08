"""Event/notification messages follow the short game style (2-5 lines)."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")
os.environ["DRAGON_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "msg.db")

from types import SimpleNamespace as N  # noqa: E402

from handlers import battle as bt  # noqa: E402
from handlers import chests as ch  # noqa: E402
from handlers import growth as gr  # noqa: E402
from utils.text import reward_card  # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append(bool(cond))
    print(("✅" if cond else "❌"), name, extra if not cond else "")


def lines(text):
    return [ln for ln in text.split("\n") if ln.strip()]


def main():
    # --- the shared currency reward card ------------------------------------
    card = reward_card({"obsidian": 500, "aether": 3})
    check("reward card matches the spec",
          card == "🎉 جایزه گرفتی!\n\n🪨 +۵۰۰\n✨ +۳", repr(card))
    check("reward card is short", len(lines(card)) <= 5, card)
    check("zero rewards are omitted",
          "✨" not in reward_card({"obsidian": 10, "aether": 0}))
    check("empty rewards degrade safely", lines(reward_card({})) == ["🎉 جایزه گرفتی!"])
    check("reward order is stable",
          lines(reward_card({"fish": 1, "obsidian": 2, "xp": 3}))[1:]
          == ["⭐ +۳ XP", "🪨 +۲", "🐟 +۱"])

    # --- chest --------------------------------------------------------------
    check("chest spawn text", ch.CHEST_TEXT == "🎁 صندوق پیدا شد!", ch.CHEST_TEXT)
    check("chest button", ch.CHEST_BUTTON_TEXT == "🎁 باز کردن", ch.CHEST_BUTTON_TEXT)
    opened = ch.format_rewards({"obsidian": 500, "aether": 2, "meat": 10}, opener="Ali")
    check("chest opened matches the spec",
          opened == "🎁 صندوق باز شد!\n\n👤 Ali\n\n🪨 +۵۰۰\n✨ +۲\n🥩 +۱۰", repr(opened))
    check("chest reward has no repeated currency words",
          "ابسیدین" not in opened and "اتر" not in opened, opened)
    check("chest message is short", len(lines(opened)) <= 5, opened)

    # --- combat -------------------------------------------------------------
    dragon = N(name="آذر", hp=180, max_hp=200, level=5)
    enemy = N(emoji="👹", name="هیولا", hp=100, max_hp=100)
    start = bt.start_text("آذر", enemy)
    check("battle start has the VS line",
          "🐉 آذر VS 👹 هیولا" in start, start)
    check("battle start is short", len(lines(start)) <= 5, start)

    turn = bt.turn_text(N(dragon=dragon, enemy=enemy, dragon_damage=25,
                          enemy_damage=0, enemy_hp_after=75))
    check("attack shows «Damage»", turn.startswith("🔥 ۲۵ Damage"), turn)

    win = bt.victory_text(N(dragon=dragon, enemy=enemy, xp_gained=50,
                            obsidian=200, aether=0, level_ups=[]))
    check("win title is 🏆 پیروزی!", win.startswith("🏆 پیروزی!"), win)
    check("win shows XP and obsidian",
          "⭐ +۵۰ XP" in win and "🪨 +۲۰۰" in win, win)

    # --- level up -----------------------------------------------------------
    ev = N(name="آذر", new_level=6, max_hp_gained=20, power_gained=5)
    lvl = gr.build_level_up_text(N(dragon=N(dragon_type="fire"), level_ups=[ev]))
    check("level up is short", len(lines(lvl)) <= 5, lvl)
    check("level up shows the numbers",
          "Lv.۶" in lvl and "+۲۰" in lvl and "+۵" in lvl, lvl)

    print()
    passed = sum(RESULTS)
    print(f"{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
