"""Global error handler for updates/jobs.

python-telegram-bot calls this whenever a handler raises. We log the full
error and, if there's a user-facing message, send a short friendly notice so
the user isn't left with no response. Network/Telegram errors are logged
without spamming the chat.
"""
from __future__ import annotations

import logging

from telegram.error import BadRequest, RetryAfter, TelegramError, TimedOut
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error

    # Network / Telegram-API problems are expected occasionally; log quietly.
    if isinstance(error, (TimedOut, RetryAfter)):
        logger.warning("Telegram network error: %s", error)
        return

    logger.error("Unhandled error while processing update %s", update, exc_info=error)

    # Only attempt a user-facing notice for genuine bugs in a message/callback.
    if isinstance(error, (TelegramError, BadRequest)):
        return

    effective_message = getattr(update, "effective_message", None)
    try:
        if effective_message is not None and getattr(effective_message, "chat", None) is not None:
            await effective_message.chat.send_message(
                "😅 مشکلی پیش اومد! یه کم بعد دوباره امتحان کن."
            )
    except Exception:
        logger.debug("Could not send error notice", exc_info=True)
