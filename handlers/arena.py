"""The ``/arena`` command, its menu and the PvP battle screens (Version 7).

Callback data: ``ar:<action>`` — actions are ``home``, ``find``, ``rank`` and
``me``. Everything is edited in place on the existing message, so a player
tapping around the arena never floods the group with new messages.

All rules live in :mod:`game.arena`; this module only renders and reports.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from game.arena import (
    REASON_LIMIT_REACHED,
    REASON_NO_DRAGON,
    REASON_NO_OPPONENT,
    ArenaResult,
    RankEntry,
    summarise_turns,
)
from utils.text import to_fa

logger = logging.getLogger(__name__)

# Callback namespace (must not collide with dg: / mk: / tr: / claim_egg: /
# open_chest: / admin:).
PREFIX = "ar:"
ACTION_HOME = "home"
ACTION_FIND = "find"
ACTION_RANK = "rank"
ACTION_ME = "me"

BTN_FIND = "⚔️ پیدا کردن حریف"
BTN_RANK = "🏆 رتبه‌بندی"
BTN_ME = "🐉 اژدهای من"
BTN_BACK = "🔙 برگشت"
BTN_AGAIN = "⚔️ نبرد دوباره"

TITLE = "🏟️ آرنا اژدها"

MSG_NO_DRAGON = "🐉 اول یه اژدها انتخاب کن!"
MSG_NO_OPPONENT = "😕 حریف هم‌زور پیدا نشد! بعداً بیا."
MSG_LIMIT = "⛔ نبردهای امروزت تموم شد!"
MSG_ERROR = "❌ خطا! دوباره بزن."


# --- keyboards --------------------------------------------------------------
def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_FIND, callback_data=f"{PREFIX}{ACTION_FIND}")],
            [InlineKeyboardButton(BTN_RANK, callback_data=f"{PREFIX}{ACTION_RANK}")],
            [InlineKeyboardButton(BTN_ME, callback_data=f"{PREFIX}{ACTION_ME}")],
            [InlineKeyboardButton(BTN_BACK, callback_data=f"{PREFIX}{ACTION_HOME}")],
        ]
    )


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(BTN_BACK, callback_data=f"{PREFIX}{ACTION_HOME}")]]
    )


def result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_AGAIN, callback_data=f"{PREFIX}{ACTION_FIND}")],
            [InlineKeyboardButton(BTN_BACK, callback_data=f"{PREFIX}{ACTION_HOME}")],
        ]
    )


# --- texts ------------------------------------------------------------------
def menu_text(stats: dict) -> str:
    """The arena home screen: title, league and today's remaining battles."""
    league = stats["league"]
    left = max(0, stats["limit"] - stats["used"])
    return (
        f"{TITLE}\n\n"
        f"{league['emoji']} لیگ {league['name']}\n"
        f"🏅 {to_fa(stats['points'])} امتیاز\n\n"
        f"⚔️ مبارزه‌های باقی‌مانده امروز:\n"
        f"{to_fa(left)}/{to_fa(stats['limit'])}"
    )


def fighter_card(fighter) -> str:
    return (
        f"🐉 {fighter.name}\n"
        f"⭐ Lv.{to_fa(fighter.level)}\n"
        f"❤️ HP: {to_fa(fighter.max_hp)}\n"
        f"⚔️ Power: {to_fa(fighter.power)}"
    )


def battle_text(result: ArenaResult) -> str:
    """The full duel: the VS card, the turn log and the outcome."""
    lines = [
        "🏟️ نبرد آرنا شروع شد!",
        "",
        fighter_card(result.challenger),
        "",
        "VS",
        "",
        fighter_card(result.opponent),
        "",
        "━━━━━━━━━━",
        "",
    ]
    for turn in summarise_turns(result.turns):
        hit = "💥 ضربه بحرانی!" if turn.crit else "💥"
        lines.append(f"⚔️ {turn.attacker} حمله کرد!")
        lines.append(f"{hit} {to_fa(turn.damage)} آسیب وارد شد")
    lines.append("")
    lines.append(outcome_text(result))
    return "\n".join(lines)


def outcome_text(result: ArenaResult) -> str:
    """Winner / loser block with the rewards."""
    if result.won:
        block = [
            "🏆 برنده شدی!",
            "",
            f"🏅 +{to_fa(result.points_delta)} امتیاز آرنا",
            f"🪨 +{to_fa(result.obsidian)} ابسیدین",
            f"✨ +{to_fa(result.xp)} تجربه",
        ]
    else:
        block = [
            "💀 شکست خوردی!",
            "",
            f"🏅 {to_fa(result.points_delta)} امتیاز آرنا",
            f"🪨 +{to_fa(result.obsidian)} ابسیدین",
            f"✨ +{to_fa(result.xp)} تجربه",
        ]
    if result.leveled_up:
        block.append("🎉 اژدهات لِوِل آپ شد!")
    if result.league_changed:
        league = result.league
        block.append(f"{league['emoji']} لیگ جدید: {league['name']}")
    left = max(0, result.battles_limit - result.battles_used)
    block.append("")
    block.append(f"⚔️ باقی‌مانده امروز: {to_fa(left)}/{to_fa(result.battles_limit)}")
    return "\n".join(block)


def ranking_text(entries: list[RankEntry], me_rank: int | None = None) -> str:
    """The leaderboard: medals for the top three, then plain numbers."""
    if not entries:
        return "🏆 رتبه آرنا\n\nهنوز کسی نجنگیده!\nاولین نفر باش. ⚔️"
    medals = ("🥇", "🥈", "🥉")
    lines = ["🏆 رتبه آرنا", ""]
    for entry in entries:
        badge = medals[entry.rank - 1] if entry.rank <= 3 else f"{to_fa(entry.rank)}."
        name = entry.username or f"بازیکن {to_fa(entry.user_id)}"
        # The medal shows the rank; the league is named on the points line so
        # the two emoji can never be mistaken for each other.
        lines.append(f"{badge} {name} {entry.league['emoji']}")
        lines.append(f"🏅 امتیاز: {to_fa(entry.points)}")
        lines.append("")
    if me_rank is not None:
        lines.append(f"📍 رتبه تو: {to_fa(me_rank)}")
    return "\n".join(lines).strip()


def my_dragon_text(stats: dict) -> str:
    """The «🐉 اژدهای من» arena profile."""
    dragon = stats["dragon"]
    if dragon is None:
        return f"{TITLE}\n\n{MSG_NO_DRAGON}"
    league = stats["league"]
    lines = [
        f"🐉 {dragon.name}",
        f"⭐ Lv.{to_fa(dragon.level)}",
        f"❤️ HP: {to_fa(dragon.max_hp)}",
        f"⚔️ Power: {to_fa(dragon.power)}",
        "",
        f"{league['emoji']} لیگ {league['name']}",
        f"🏅 امتیاز: {to_fa(stats['points'])}",
        f"🏆 برد: {to_fa(stats['wins'])}   💀 باخت: {to_fa(stats['losses'])}",
    ]
    if stats["rank"] is not None:
        lines.append(f"📍 رتبه: {to_fa(stats['rank'])}")
    upcoming = stats["next_league"]
    if upcoming is not None:
        need = upcoming["min_points"] - stats["points"]
        lines.append(f"⬆️ تا {upcoming['emoji']} {upcoming['name']}: {to_fa(need)} امتیاز")
    left = max(0, stats["limit"] - stats["used"])
    lines.append("")
    lines.append(f"⚔️ مبارزه‌های باقی‌مانده امروز:\n{to_fa(left)}/{to_fa(stats['limit'])}")
    return "\n".join(lines)


# --- telegram plumbing ------------------------------------------------------
async def _answer(query, text: str | None = None, alert: bool = False) -> None:
    try:
        await query.answer(text=text, show_alert=alert)
    except TelegramError:
        logger.debug("Could not answer arena callback", exc_info=True)


async def _edit(query, text: str, reply_markup=None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as exc:
        # Editing to identical content is not an error for us.
        if "not modified" not in str(exc).lower():
            logger.debug("Arena edit failed: %s", exc)
    except TelegramError:
        logger.debug("Arena edit failed", exc_info=True)


def _service(context):
    return context.bot_data.get("arena_service")


# --- entry points -----------------------------------------------------------
async def arena_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/arena`` — opens the arena menu."""
    user = update.effective_user
    message = update.effective_message
    if user is None or user.is_bot or message is None:
        return

    from handlers.tracking import track_from_update

    track_from_update(update, context)

    arena = _service(context)
    players = context.bot_data.get("player_repo")
    if arena is None or players is None:
        await message.reply_text(MSG_ERROR)
        return

    try:
        players.get_or_create(user.id, user.username)
        stats = arena.stats(user.id)
        await message.reply_text(menu_text(stats), reply_markup=menu_keyboard())
    except Exception:
        logger.exception("arena_command failed for user %s", user.id)
        await message.reply_text(MSG_ERROR)


async def arena_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route ``ar:<action>`` button presses."""
    query = update.callback_query
    if query is None or query.from_user is None or query.from_user.is_bot:
        return

    data = query.data or ""
    action = data[len(PREFIX):] if data.startswith(PREFIX) else ""
    user_id = query.from_user.id

    arena = _service(context)
    if arena is None:
        await _answer(query, MSG_ERROR, alert=True)
        return

    try:
        if action == ACTION_HOME:
            await _answer(query)
            await _edit(query, menu_text(arena.stats(user_id)), menu_keyboard())
        elif action == ACTION_RANK:
            await _answer(query)
            entries = arena.ranking()
            me_rank = arena.players.arena_rank_of(user_id)
            await _edit(query, ranking_text(entries, me_rank), back_keyboard())
        elif action == ACTION_ME:
            await _answer(query)
            await _edit(query, my_dragon_text(arena.stats(user_id)), back_keyboard())
        elif action == ACTION_FIND:
            await _handle_find(query, arena, user_id)
        # Unknown actions are ignored on purpose (stale buttons).
    except Exception:
        logger.exception("arena_callback failed (action=%r)", action)
        await _answer(query, MSG_ERROR, alert=True)


async def _handle_find(query, arena, user_id: int) -> None:
    """Matchmake, fight and show the result — all in the same message."""
    chat_id = query.message.chat_id if query.message is not None else None
    result = arena.fight(user_id, chat_id=chat_id)

    if not result.ok:
        if result.reason == REASON_NO_DRAGON:
            await _answer(query, MSG_NO_DRAGON, alert=True)
        elif result.reason == REASON_NO_OPPONENT:
            await _answer(query, MSG_NO_OPPONENT, alert=True)
        elif result.reason == REASON_LIMIT_REACHED:
            await _answer(query, MSG_LIMIT, alert=True)
        else:
            await _answer(query, MSG_ERROR, alert=True)
        return

    await _answer(query, "🏆 بردی!" if result.won else "💀 باختی!")
    await _edit(query, battle_text(result), result_keyboard())
