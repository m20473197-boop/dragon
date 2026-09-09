"""Event/notification messages follow the short game style (2-5 lines)."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")
os.environ["DRAGON_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "msg.db")

from types import SimpleNamespace as N  # noqa: E402

from handlers import arena as ar  # noqa: E402
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

    # --- arena PvP ------------------------------------------------------------
    from game.arena import ArenaResult, Fighter, Turn
    me = Fighter(1, "Ali", 10, "آذر", "🐉", level=10, max_hp=300, hp=300, power=120)
    rival = Fighter(2, "Reza", 20, "رعد", "🐉", level=11, max_hp=320, hp=0, power=130)

    card = ar.fighter_card(me)
    check("fighter card matches the spec",
          card == "🐉 آذر\n⭐ Lv.۱۰\n❤️ HP: ۳۰۰\n⚔️ Power: ۱۲۰", repr(card))
    check("fighter card is short", len(lines(card)) <= 5, card)

    stats = {"points": 250, "wins": 3, "losses": 1, "league":
             {"emoji": "🥉", "name": "برنز"}, "used": 3, "limit": 10,
             "rank": 2, "next_league": {"emoji": "🥈", "name": "نقره",
                                        "min_points": 500}, "dragon": None}
    menu = ar.menu_text(stats)
    check("arena menu title", menu.startswith("🏟️ آرنا اژدها"), menu)
    check("arena menu shows the daily counter", "۷/۱۰" in menu, menu)
    check("arena menu is short", len(lines(menu)) <= 6, menu)

    res = ArenaResult(ok=True, challenger=me, opponent=rival, winner_id=1,
                      turns=[Turn("آذر", "رعد", 35, False, 285)],
                      points_delta=25, points_total=275, obsidian=500, xp=30,
                      league={"emoji": "🥉", "name": "برنز"},
                      battles_used=4, battles_limit=10)
    won = ar.outcome_text(res)
    check("win title is 🏆 برنده شدی!", won.startswith("🏆 برنده شدی!"), won)
    check("win shows arena points", "🏅 +۲۵ امتیاز آرنا" in won, won)
    check("win shows obsidian", "🪨 +۵۰۰ ابسیدین" in won, won)
    check("win shows the remaining battles", "۶/۱۰" in won, won)

    lost = ArenaResult(ok=True, challenger=me, opponent=rival, winner_id=2,
                       turns=[], points_delta=-10, points_total=0,
                       obsidian=100, xp=10,
                       league={"emoji": "🥉", "name": "برنز"},
                       battles_used=5, battles_limit=10)
    defeat = ar.outcome_text(lost)
    check("loss title is 💀 شکست خوردی!", defeat.startswith("💀 شکست خوردی!"), defeat)

    battle = ar.battle_text(res)
    check("battle screen announces the start",
          battle.startswith("🏟️ نبرد آرنا شروع شد!"), battle)
    check("battle screen has the VS separator", "\nVS\n" in battle, battle)
    check("battle screen shows the attack line", "⚔️ آذر حمله کرد!" in battle, battle)
    check("battle screen shows the damage", "💥 ۳۵ آسیب وارد شد" in battle, battle)

    entries = [ar.RankEntry(1, 11, "Ali", 2500, 20, 3, {"emoji": "🥇", "name": "طلا"}),
               ar.RankEntry(2, 12, "Reza", 2000, 15, 5, {"emoji": "🥈", "name": "نقره"}),
               ar.RankEntry(3, 13, "Sara", 1500, 10, 8, {"emoji": "🥈", "name": "نقره"})]
    rank = ar.ranking_text(entries)
    check("ranking title", rank.startswith("🏆 رتبه آرنا"), rank)
    check("ranking uses the three medals",
          "🥇 Ali" in rank and "🥈 Reza" in rank and "🥉 Sara" in rank, rank)
    check("ranking shows each player's league badge",
          "🥇 Ali 🥇" in rank and "🥈 Reza 🥈" in rank, rank)
    check("ranking shows points", "امتیاز: ۲۵۰۰" in rank, rank)
    empty = ar.ranking_text([])
    check("empty ranking is friendly", "هنوز کسی نجنگیده" in empty, empty)

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
