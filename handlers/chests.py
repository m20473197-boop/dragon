"""Random chest messages, the open button and its callback.

A chest is announced in the group with a single inline button. The first user
to press it opens the chest and receives the rewards.

The original chest message is then **edited in place** into the result (opener
+ rewards) and its button is removed — no second message is sent, so the group
is not spammed and a chest can never be pressed twice.
"""
from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import ContextTypes

from utils.text import reward_card

logger = logging.getLogger(__name__)

# Callback data looks like "open_chest:42".
CHEST_PREFIX = "open_chest:"

# Telegram can be slow to answer inside scheduled jobs; give the HTTP call a
# generous but bounded budget so a hiccup never blocks the job queue forever.
SEND_READ_TIMEOUT = 30.0
SEND_WRITE_TIMEOUT = 30.0
SEND_CONNECT_TIMEOUT = 15.0
SEND_POOL_TIMEOUT = 15.0
SEND_RETRIES = 2

CHEST_TEXT = "🎁 صندوق پیدا شد!"
CHEST_BUTTON_TEXT = "🎁 باز کردن"
CHEST_OPENED_TITLE = "🎁 صندوق باز شد!"


def build_chest_keyboard(chest_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(CHEST_BUTTON_TEXT, callback_data=f"{CHEST_PREFIX}{chest_id}")]]
    )


def format_rewards(rewards: dict, opener: str | None = None) -> str:
    """Render the opened-chest message that replaces the spawn message.

    Uses the shared reward card so a chest reward looks exactly like every
    other reward in the game::

        🎁 صندوق باز شد!

        👤 Ali

        🪨 +۸۵۰
        ✨ +۳
        🥩 +۱۵
    """
    return reward_card(rewards, title=CHEST_OPENED_TITLE, who=opener)


async def safe_send_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    *,
    what: str = "message",
    retries: int = SEND_RETRIES,
    **kwargs,
) -> Message | None:
    """Send a message without ever raising into a scheduled job.

    Timeouts and transient network errors are retried a couple of times with a
    short backoff; blocked bots / invalid chat ids are logged once and skipped.
    Returns the sent :class:`Message`, or ``None`` when delivery failed.
    """
    kwargs.setdefault("read_timeout", SEND_READ_TIMEOUT)
    kwargs.setdefault("write_timeout", SEND_WRITE_TIMEOUT)
    kwargs.setdefault("connect_timeout", SEND_CONNECT_TIMEOUT)
    kwargs.setdefault("pool_timeout", SEND_POOL_TIMEOUT)

    for attempt in range(1, max(1, retries) + 1):
        try:
            return await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        # NOTE: BadRequest/Forbidden must be caught BEFORE NetworkError —
        # in python-telegram-bot BadRequest is a subclass of NetworkError.
        except Forbidden as exc:
            logger.warning(
                "Cannot send %s to chat %s (bot blocked or removed): %s", what, chat_id, exc
            )
            return None
        except BadRequest as exc:
            logger.warning("Cannot send %s to chat %s (invalid chat/message): %s", what, chat_id, exc)
            return None
        except (TimedOut, NetworkError) as exc:
            logger.warning(
                "Timeout while sending %s to chat %s (attempt %s/%s): %s",
                what, chat_id, attempt, retries, exc,
            )
            if attempt < retries:
                await asyncio.sleep(2.0 * attempt)
        except RetryAfter as exc:
            wait = float(getattr(exc, "retry_after", 5) or 5)
            logger.warning(
                "Flood control while sending %s to chat %s; waiting %ss", what, chat_id, wait
            )
            if attempt < retries:
                await asyncio.sleep(min(wait, 30.0))
        except TelegramError:
            logger.warning("Failed to send %s to chat %s", what, chat_id, exc_info=True)
            return None
        except Exception:  # never let a scheduled job die
            logger.exception("Unexpected error while sending %s to chat %s", what, chat_id)
            return None

    logger.error("Giving up sending %s to chat %s after %s attempts", what, chat_id, retries)
    return None


async def _safe_answer(query, text: str | None = None, alert: bool = False) -> None:
    try:
        await query.answer(text, show_alert=alert)
    except (BadRequest, TelegramError):
        pass


async def _edit_chest_message(
    context: ContextTypes.DEFAULT_TYPE,
    query,
    chest_id: int,
    text: str,
    chest=None,
) -> bool:
    """Rewrite the chest's own message with ``text`` and remove its button.

    Editing via the callback query is tried first (it always targets the exact
    message that was pressed). If that message is unavailable, the stored
    ``chests.message_id`` from spawn time is used as a fallback. Failures are
    logged, never raised — a chest is already granted in the database by this
    point, so a failed edit must not break anything.
    """
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=None)
        return True
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            return True
        logger.warning("Could not edit chest %s message: %s", chest_id, exc)
    except TelegramError:
        logger.warning("Could not edit chest %s message", chest_id, exc_info=True)
    except Exception:
        logger.exception("Unexpected error editing chest %s message", chest_id)

    # Fallback: the message_id saved when the chest was spawned.
    chat_id = getattr(chest, "group_id", None)
    message_id = getattr(chest, "message_id", None)
    if chat_id is None or message_id is None:
        logger.warning(
            "Chest %s has no stored message to edit; result not shown", chest_id
        )
        return False
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=None,
            read_timeout=SEND_READ_TIMEOUT,
            write_timeout=SEND_WRITE_TIMEOUT,
            connect_timeout=SEND_CONNECT_TIMEOUT,
            pool_timeout=SEND_POOL_TIMEOUT,
        )
        return True
    except (BadRequest, Forbidden, TelegramError):
        logger.warning(
            "Fallback edit of chest %s (chat %s, message %s) failed",
            chest_id, chat_id, message_id, exc_info=True,
        )
    except Exception:
        logger.exception("Unexpected error in fallback edit of chest %s", chest_id)
    return False


async def open_chest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a press on the «باز کردن صندوق» button."""
    query = update.callback_query
    if query is None or query.from_user is None or query.from_user.is_bot:
        return

    chest_service = context.bot_data["chest_service"]
    player_repo = context.bot_data["player_repo"]

    try:
        chest_id = int((query.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        await _safe_answer(query)
        return

    user = query.from_user

    try:
        player_repo.get_or_create(user.id, user.username)
        result = chest_service.open_chest(chest_id, user.id)

        if not result.success:
            if result.reason == "already_opened":
                await _safe_answer(query, "😔 یکی زودتر باز کرد!", alert=True)
            elif result.reason == "expired":
                await _safe_answer(query, "⌛ منقضی شده.", alert=True)
            else:
                await _safe_answer(query, "🚧 پیدا نشد.", alert=True)
            # Make sure a dead chest keeps no clickable button.
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except (BadRequest, TelegramError):
                pass
            return

        await _safe_answer(query, "🎁 مال تو شد!")

        # Edit the ORIGINAL chest message into the result and drop its button,
        # rather than sending a new message.
        mention = user.mention_html(user.full_name or f"کاربر {user.id}")
        text = format_rewards(result.rewards, opener=mention)
        await _edit_chest_message(context, query, chest_id, text, chest=result.chest)
    except Exception:
        logger.exception("Error while opening chest %s", chest_id)
        await _safe_answer(query, "❌ خطا! دوباره بزن.", alert=True)
