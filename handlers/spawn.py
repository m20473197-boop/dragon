"""Egg spawning messages, inline keyboard and the claim callback."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from game.eggs import egg_display

logger = logging.getLogger(__name__)

# Callback data looks like "claim_egg:42".
CLAIM_PREFIX = "claim_egg:"

SPAWN_TEXT = "🥚 تخم اژدها پیدا شد!"
CLAIM_BUTTON_TEXT = "🥚 نگهداری"


def build_spawn_keyboard(egg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(CLAIM_BUTTON_TEXT, callback_data=f"{CLAIM_PREFIX}{egg_id}")]]
    )


async def _safe_answer(query, text: str | None = None, alert: bool = False) -> None:
    """Answer a callback query, ignoring "query too old / answered" errors."""
    try:
        await query.answer(text, show_alert=alert)
    except (BadRequest, TelegramError):
        pass


async def claim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a press on the «نگهداری از تخم» button."""
    query = update.callback_query
    if query is None or query.from_user is None or query.from_user.is_bot:
        return

    egg_service = context.bot_data["egg_service"]
    player_repo = context.bot_data["player_repo"]

    try:
        egg_id = int((query.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        await _safe_answer(query)
        return

    user = query.from_user

    try:
        # Make sure the clicker is registered as a player before claiming.
        player_repo.get_or_create(user.id, user.username)
        claimed, current = egg_service.claim_egg(egg_id, user.id)

        if claimed is not None:
            # This user won the race.
            emoji, name = egg_display(claimed.egg_type)
            await _safe_answer(query, "🎉 مال تو شد!")

            # Remove the button so nobody else can press it.
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except (BadRequest, TelegramError):
                pass  # message unchanged / too old / missing — not fatal

            chat_id = query.message.chat_id if query.message is not None else user.id
            mention = user.mention_html(user.full_name or f"کاربر {user.id}")
            text = f"🥚 تخم برداشته شد!\n\n👤 {mention}\n{emoji} {name}\n⏳ در حال پرورش..."
            try:
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            except (BadRequest, TelegramError):
                # Could not post to the group (bot removed / blocked) — the egg
                # is already safely claimed, so just log and move on.
                logger.warning("Could not announce claim for egg %s", egg_id, exc_info=True)
        else:
            # Someone else won, or the egg expired.
            if current is not None and current.owner_id is not None:
                await _safe_answer(query, "😔 یکی زودتر برداشت!", alert=True)
            else:
                await _safe_answer(query, "⌛ منقضی شده.", alert=True)
    except Exception:
        # Never let an error leave the user's spinner hanging.
        logger.exception("Error while claiming egg %s", egg_id)
        await _safe_answer(query, "❌ خطا! دوباره بزن.", alert=True)
