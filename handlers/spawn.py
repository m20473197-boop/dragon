"""Egg spawning message, inline keyboard and the claim callback.

An egg is announced with ONE message carrying a single button. The first user
to press it collects the egg, and that same message is **edited in place**
into the result (no second message is ever sent) with its button removed, so
the egg can never be collected twice and the group is not spammed.

The result message is temporary: a deletion deadline is stored on the egg row
so ``handlers.cleanup`` removes it a few minutes later, even across a restart.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from handlers.cleanup import deletion_deadline

logger = logging.getLogger(__name__)

# Callback data looks like "claim_egg:42".
CLAIM_PREFIX = "claim_egg:"

SPAWN_TEXT = "🥚 یک تخم اژدها پیدا شد!"
CLAIM_BUTTON_TEXT = "🥚 نگهداری از تخم"
CLAIMED_TITLE = "🥚 تخم برداشته شد!"


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


async def _edit_egg_message(
    context: ContextTypes.DEFAULT_TYPE, query, egg, text: str
) -> bool:
    """Rewrite the egg's own message with ``text`` and remove its button.

    Editing through the callback query is tried first (it always targets the
    exact message that was pressed); the ``eggs.message_id`` stored at spawn
    time is the fallback. Failures are logged, never raised — the egg is
    already claimed in the database, so a failed edit must break nothing.
    """
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=None)
        return True
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            return True
        logger.warning("Could not edit egg %s message: %s", egg.id, exc)
    except TelegramError:
        logger.warning("Could not edit egg %s message", egg.id, exc_info=True)
    except Exception:
        logger.exception("Unexpected error editing egg %s message", egg.id)

    if not getattr(egg, "message_id", None):
        logger.warning("Egg %s has no stored message to edit; result not shown", egg.id)
        return False
    try:
        await context.bot.edit_message_text(
            chat_id=egg.chat_id,
            message_id=egg.message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=None,
        )
        return True
    except (BadRequest, TelegramError):
        logger.warning(
            "Fallback edit of egg %s (chat %s, message %s) failed",
            egg.id, egg.chat_id, egg.message_id, exc_info=True,
        )
    except Exception:
        logger.exception("Unexpected error in fallback edit of egg %s", egg.id)
    return False


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
            await _safe_answer(query, "🎉 مال تو شد!")

            # Edit the ORIGINAL spawn message into the result and drop its
            # button, instead of sending a new message.
            mention = user.mention_html(user.full_name or f"کاربر {user.id}")
            text = f"{CLAIMED_TITLE}\n\n👤 بازیکن: {mention}"
            await _edit_egg_message(context, query, claimed, text)

            # Schedule the result message for deletion (persisted, so it also
            # happens if the bot restarts in the meantime).
            try:
                egg_service.eggs.set_delete_after(claimed.id, deletion_deadline())
            except Exception:
                logger.warning(
                    "Could not schedule cleanup for egg %s", claimed.id, exc_info=True
                )
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
