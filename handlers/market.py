"""Market (بازار) command and tool upgrade screens.

Layout:

    🏪 بازار                -> categories
      🎣 ابزار ماهیگیری      -> current rod level, with an [⬆️ ارتقا] button
      🏹 ابزار شکار          -> current weapon level, with an [⬆️ ارتقا] button

The market sells TOOL UPGRADES only. Food and dragon eggs are not for sale:
food comes from 🏹 hunting, 🎣 fishing and 🎁 chests, and eggs come from random
spawns and rewards. The cold storage and egg systems are untouched.

Everything is priced in 🪨 obsidian. ``game.tools`` performs the guarded spend,
so a player can never overspend; this module only renders the UI.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from config import MARKET_CATEGORIES, MARKET_ITEMS, TOOL_MAX_LEVEL
from game.tools import ROD, WEAPON, is_max_level, reward_range, tool_display, upgrade_cost
from utils.text import to_fa

logger = logging.getLogger(__name__)

# Callback data: "mk:<action>[:<category>]".
PREFIX = "mk:"
ACTION_HOME = "home"
ACTION_CATEGORY = "cat"
ACTION_TOOL_UP = "toolup"   # mk:toolup:<rod|hunt>

# Every market category is a tool screen.
TOOL_CATEGORIES = {"rod": ROD, "hunt": WEAPON}

MARKET_TITLE = "🏪 بازار"
CURRENCY = "🪨"


# --- keyboards --------------------------------------------------------------
def categories_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{spec['emoji']} {spec['short']}",
                callback_data=f"{PREFIX}{ACTION_CATEGORY}:{key}",
            )
        ]
        for key, spec in MARKET_CATEGORIES.items()
    ]
    # «🔙» closes the market back to its main screen.
    rows.append([InlineKeyboardButton("🔙", callback_data=f"{PREFIX}{ACTION_HOME}")])
    return InlineKeyboardMarkup(rows)


def tool_keyboard(category: str, at_max: bool) -> InlineKeyboardMarkup:
    """«⬆️ ارتقا» for a tool screen (hidden once the tool is maxed)."""
    rows = []
    if not at_max:
        rows.append(
            [
                InlineKeyboardButton(
                    "⬆️ ارتقا",
                    callback_data=f"{PREFIX}{ACTION_TOOL_UP}:{category}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("🔙", callback_data=f"{PREFIX}{ACTION_HOME}")])
    return InlineKeyboardMarkup(rows)


# --- texts ------------------------------------------------------------------
def market_text(balance: int) -> str:
    return (
        f"{MARKET_TITLE}\n\n"
        f"💰 {to_fa(balance)} 🪨\n\n"
        "انتخاب کن:"
    )


def tool_text(category: str, level: int, balance: int) -> str:
    """Tool screen: the tool, its level, the next upgrade cost and the balance.

    Example::

        🎣 ابزار ماهیگیری

        🎣 قلاب فعلی:
        Lv.۳ — قلاب فولادی
        🐟 ۱۲-۲۰

        ⬆️ ارتقا: 🪨 ۱۰۰۰۰
        💰 ۵۰۰۰ 🪨
    """
    kind = TOOL_CATEGORIES[category]
    spec = MARKET_CATEGORIES[category]
    emoji, name = tool_display(kind, level)
    low, high = reward_range(kind, level)
    res_emoji = "🐟" if kind == ROD else "🥩"
    label = "قلاب فعلی" if kind == ROD else "ابزار شکار"

    lines = [
        f"{spec['emoji']} {spec['name']}",
        "",
        f"{emoji} {label}:",
        f"Lv.{to_fa(level)} — {name}",
        f"{res_emoji} {to_fa(low)}-{to_fa(high)}",
        "",
    ]
    if is_max_level(level):
        lines.append(f"🏆 حداکثر سطح! (Lv.{to_fa(TOOL_MAX_LEVEL)})")
    else:
        lines.append(f"⬆️ ارتقا: 🪨 {to_fa(upgrade_cost(kind, level))}")
    lines.append(f"💰 {to_fa(balance)} 🪨")
    return "\n".join(lines)


def tool_upgraded_text(category: str, result) -> str:
    """Success card after a tool upgrade."""
    kind = TOOL_CATEGORIES[category]
    emoji, name = tool_display(kind, result.level)
    label = "قلاب" if kind == ROD else "ابزار شکار"
    lines = [
        "🎉 ارتقا موفق!",
        "",
        f"{emoji} {label}:",
        f"Lv.{to_fa(result.previous_level)} ➜ Lv.{to_fa(result.level)}",
        f"✨ {name}",
        "",
        f"🪨 -{to_fa(result.spent)}   💰 {to_fa(result.balance)}",
    ]
    return "\n".join(lines)


# --- command ----------------------------------------------------------------
async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«بازار» — open the market with its category buttons."""
    user = update.effective_user
    message = update.effective_message
    context.bot_data["player_repo"].get_or_create(user.id, user.username)
    balance = context.bot_data["market_service"].balance(user.id)

    await message.reply_text(market_text(balance), reply_markup=categories_keyboard())


# --- callbacks --------------------------------------------------------------
async def market_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route every «mk:» button press."""
    query = update.callback_query
    if query is None or query.from_user is None or query.from_user.is_bot:
        return

    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    user = query.from_user
    market = context.bot_data["market_service"]

    try:
        context.bot_data["player_repo"].get_or_create(user.id, user.username)

        if action == ACTION_HOME:
            await _answer(query)
            await _edit(query, market_text(market.balance(user.id)), categories_keyboard())
            return

        category = parts[2] if len(parts) > 2 else ""
        if category not in MARKET_ITEMS:
            await _answer(query)
            return

        # --- tool screens (🎣 rod / 🏹 weapon) ---
        if category in TOOL_CATEGORIES:
            tools = context.bot_data["tool_service"]
            kind = TOOL_CATEGORIES[category]

            if action == ACTION_CATEGORY:
                level = tools.level(user.id, kind)
                await _answer(query)
                await _edit(
                    query,
                    tool_text(category, level, tools.balance(user.id)),
                    tool_keyboard(category, is_max_level(level)),
                )
                return

            if action == ACTION_TOOL_UP:
                result = tools.upgrade(user.id, kind)
                if not result.success:
                    if result.reason == "max_level":
                        await _answer(query, "🏆 حداکثر سطحه!", alert=True)
                    else:
                        await _answer(query, "❌ ابسیدین کافی نیست!", alert=True)
                    await _edit(
                        query,
                        tool_text(category, result.level, tools.balance(user.id)),
                        tool_keyboard(category, is_max_level(result.level)),
                    )
                    return

                await _answer(query, "🎉 ارتقا موفق!")
                await _edit(
                    query,
                    tool_upgraded_text(category, result),
                    tool_keyboard(category, is_max_level(result.level)),
                )
                return

            await _answer(query)
            return

        await _answer(query)
    except Exception:
        logger.exception("Market callback failed for %s", query.data)
        await _answer(query, "❌ خطا! دوباره بزن.", alert=True)


# --- helpers ----------------------------------------------------------------
async def _edit(query, text: str, markup: InlineKeyboardMarkup | None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except (BadRequest, TelegramError):
        logger.debug("Could not edit market message", exc_info=True)


async def _answer(query, text: str | None = None, alert: bool = False) -> None:
    try:
        await query.answer(text, show_alert=alert)
    except (BadRequest, TelegramError):
        pass
