"""Dragon Treasury (خزانه) — the player's inventory screen.

Three screens, all rendered into the SAME message via editing:

    🏰 خزانه اژدها     -> currencies, with [🥩 غذا] [🥚 تخم‌ها] buttons
      🥩 غذا           -> cold storage contents
      🥚 تخم‌ها         -> eggs per type
      🔙 برگشت          -> back to the treasury home

This is a display-only feature: it reads the existing currency, cold storage
and egg data through :class:`game.treasury.TreasuryService` and never writes
anything, so no gameplay logic or balance is affected.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from utils.text import to_fa

logger = logging.getLogger(__name__)

# Callback data: "tr:<action>".
PREFIX = "tr:"
ACTION_HOME = "home"
ACTION_FOOD = "food"
ACTION_EGGS = "eggs"

TREASURY_TITLE = "🏰 خزانه اژدها"
STORAGE_TITLE = "❄️ سردخانه"
EGGS_TITLE = "🥚 تخم‌های من:"

BUTTON_FOOD = "🥩 غذا"
BUTTON_EGGS = "🥚 تخم‌ها"
BUTTON_BACK = "🔙 برگشت"


# --- keyboards --------------------------------------------------------------
def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BUTTON_FOOD, callback_data=f"{PREFIX}{ACTION_FOOD}")],
            [InlineKeyboardButton(BUTTON_EGGS, callback_data=f"{PREFIX}{ACTION_EGGS}")],
        ]
    )


def section_keyboard() -> InlineKeyboardMarkup:
    """Sub-screens only need a way back to the treasury."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(BUTTON_BACK, callback_data=f"{PREFIX}{ACTION_HOME}")]]
    )


# --- texts ------------------------------------------------------------------
def treasury_text(contents) -> str:
    """Home screen: the title and the two currencies, nothing else."""
    return (
        f"{TREASURY_TITLE}\n\n"
        f"🪨 ابسیدین: {to_fa(contents.obsidian)}\n"
        f"✨ اتر: {to_fa(contents.aether)}"
    )


def food_text(contents) -> str:
    """Cold storage contents (zeros are shown, never hidden)."""
    return (
        f"{STORAGE_TITLE}\n\n"
        f"🥩 گوشت: {to_fa(contents.meat)}\n"
        f"🐟 ماهی: {to_fa(contents.fish)}"
    )


def eggs_text(contents) -> str:
    """One line per egg type, so an empty type still reads «0»."""
    lines = [EGGS_TITLE, ""]
    for stack in contents.eggs:
        lines.append(f"{stack.emoji} {stack.name}: {to_fa(stack.count)}")
    return "\n".join(lines)


# --- command ----------------------------------------------------------------
async def treasury_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«خزانه» — open the treasury."""
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    try:
        context.bot_data["player_repo"].get_or_create(user.id, user.username)
        contents = context.bot_data["treasury_service"].contents(user.id)
        await message.reply_text(treasury_text(contents), reply_markup=home_keyboard())
    except Exception:
        logger.exception("Treasury command failed for user %s", user.id)
        try:
            await message.reply_text("❌ خطا! دوباره امتحان کن.")
        except (BadRequest, TelegramError):
            pass


# --- callbacks --------------------------------------------------------------
async def treasury_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route every «tr:» button press by editing the same message."""
    query = update.callback_query
    if query is None or query.from_user is None or query.from_user.is_bot:
        return

    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    user = query.from_user

    try:
        context.bot_data["player_repo"].get_or_create(user.id, user.username)
        contents = context.bot_data["treasury_service"].contents(user.id)

        if action == ACTION_FOOD:
            await _answer(query)
            await _edit(query, food_text(contents), section_keyboard())
            return

        if action == ACTION_EGGS:
            await _answer(query)
            await _edit(query, eggs_text(contents), section_keyboard())
            return

        if action == ACTION_HOME:
            await _answer(query)
            await _edit(query, treasury_text(contents), home_keyboard())
            return

        # Unknown action: stop the spinner without touching the message.
        await _answer(query)
    except Exception:
        logger.exception("Treasury callback failed for %s", query.data)
        await _answer(query, "❌ خطا! دوباره بزن.", alert=True)


# --- helpers ----------------------------------------------------------------
async def _edit(query, text: str, markup: InlineKeyboardMarkup | None) -> None:
    """Edit in place; an unchanged message is not an error."""
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            logger.debug("Could not edit treasury message: %s", exc)
    except TelegramError:
        logger.debug("Could not edit treasury message", exc_info=True)


async def _answer(query, text: str | None = None, alert: bool = False) -> None:
    try:
        await query.answer(text, show_alert=alert)
    except (BadRequest, TelegramError):
        pass
