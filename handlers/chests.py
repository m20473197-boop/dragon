"""Random chest messages, the open button and its callback.

A chest is announced in the group with a single inline button. The first user
to press it opens the chest and receives the rewards; the button is then
removed so nobody else can try.
"""
from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import ContextTypes

from config import CURRENCIES, FOODS
from utils.text import to_fa

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

CHEST_TEXT = "🎁 یک صندوق مرموز پیدا شد!\nبرای باز کردنش روی دکمه بزن 👇"
CHEST_BUTTON_TEXT = "🎁 باز کردن صندوق"


def build_chest_keyboard(chest_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(CHEST_BUTTON_TEXT, callback_data=f"{CHEST_PREFIX}{chest_id}")]]
    )


def format_rewards(rewards: dict) -> str:
    """Render the reward lines of an opened chest.

    Example::

        🎁 صندوق باز شد!

        🪨 +۸۵۰ ابسیدین
        ✨ +۳ اتر
        🥩 +۱۵ گوشت
        🐟 +۲۰ ماهی
    """
    lines = ["🎁 صندوق باز شد!", ""]
    for key in ("obsidian", "aether"):
        amount = rewards.get(key, 0)
        if amount:
            info = CURRENCIES[key]
            lines.append(f"{info['emoji']} +{to_fa(amount)} {info['name']}")
    for key in ("meat", "fish"):
        amount = rewards.get(key, 0)
        if amount:
            info = FOODS[key]
            lines.append(f"{info['emoji']} +{to_fa(amount)} {info['name']}")
    return "\n".join(lines)


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
                await _safe_answer(query, "😔 یکی دیگه زودتر این صندوق رو باز کرده بود!", alert=True)
            elif result.reason == "expired":
                await _safe_answer(query, "این صندوق دیگه در دسترس نیست.", alert=True)
            else:
                await _safe_answer(query, "این صندوق پیدا نشد.", alert=True)
            # Make sure a dead chest keeps no clickable button.
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except (BadRequest, TelegramError):
                pass
            return

        await _safe_answer(query, "🎁 صندوق مال تو شد!")

        # Remove the button so the chest cannot be pressed again.
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except (BadRequest, TelegramError):
            pass

        mention = user.mention_html(user.full_name or f"کاربر {user.id}")
        text = f"{mention}\n{format_rewards(result.rewards)}"
        chat_id = query.message.chat_id if query.message is not None else user.id
        sent = await safe_send_message(
            context, chat_id, text, what=f"chest {chest_id} rewards", parse_mode="HTML"
        )
        if sent is None:
            logger.warning("Could not announce rewards of chest %s in chat %s", chest_id, chat_id)
    except Exception:
        logger.exception("Error while opening chest %s", chest_id)
        await _safe_answer(query, "خطایی پیش اومد؛ دوباره امتحان کن.", alert=True)
