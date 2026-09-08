"""Global error handler for updates/jobs.

python-telegram-bot calls this whenever a handler raises. We log the full
error and, if there's a user-facing message, send a short friendly notice so
the user isn't left with no response. Network/Telegram errors are logged
without spamming the chat.

Special case — :class:`telegram.error.Conflict`: Telegram allows only one
``getUpdates`` consumer per token. If a second copy of the bot is started (an
old process still running, a second server, or a webhook left registered) the
polling loop raises ``Conflict`` on *every* poll, which floods the log with
identical tracebacks. Those are collapsed into one clear explanation plus an
occasional reminder, without stopping the bot: whichever instance wins the
race keeps working, and the loser recovers automatically once the duplicate
is stopped.
"""
from __future__ import annotations

import logging
import time

from telegram.error import BadRequest, Conflict, RetryAfter, TelegramError, TimedOut
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# --- Conflict (duplicate bot instance) throttling ---------------------------
# How often the "another instance is running" reminder may be logged.
CONFLICT_LOG_INTERVAL_SECONDS: float = 300.0

CONFLICT_MESSAGE = (
    "Telegram Conflict: another instance of this bot is already polling with "
    "the same token (terminated by other getUpdates request). Only ONE bot "
    "instance may run at a time — stop the other process/server, or remove a "
    "leftover webhook (deleteWebhook), then restart. Polling will keep "
    "retrying in the background."
)

# Module-level so the counter survives across handler invocations.
_conflict_state: dict[str, float] = {"last_log": 0.0, "count": 0.0}


def _handle_conflict(now: float | None = None) -> bool:
    """Log a duplicate-instance conflict at most once per interval.

    Returns True when this call actually emitted a log line (used by tests).
    """
    now = now if now is not None else time.monotonic()
    _conflict_state["count"] += 1
    count = int(_conflict_state["count"])
    last = _conflict_state["last_log"]

    # Always explain the very first one; after that, throttle hard.
    if count == 1:
        logger.error("%s", CONFLICT_MESSAGE)
        _conflict_state["last_log"] = now
        return True

    if now - last >= CONFLICT_LOG_INTERVAL_SECONDS:
        logger.error(
            "%s (repeated %s times in the last %s seconds)",
            CONFLICT_MESSAGE, count - 1, int(now - last),
        )
        _conflict_state["last_log"] = now
        return True

    # Suppressed: keep it at debug level so nothing is silently lost.
    logger.debug("Telegram Conflict suppressed (occurrence %s)", count)
    return False


def reset_conflict_state() -> None:
    """Forget throttling state (used by tests and on a clean restart)."""
    _conflict_state["last_log"] = 0.0
    _conflict_state["count"] = 0.0


class ConflictLogFilter(logging.Filter):
    """Collapse python-telegram-bot's own Conflict tracebacks.

    The polling loop inside ``telegram.ext.Updater`` catches network errors
    itself and logs them with its own logger — those records never reach the
    application error handler. Without this filter a duplicate instance
    produces one full traceback per poll (several per second). The filter
    drops those records and feeds them to the same throttle instead, so the
    operator sees one clear explanation rather than an endless wall of text.

    Everything that is not a Conflict passes through untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        exc_info = record.exc_info
        error = exc_info[1] if exc_info else None
        if isinstance(error, Conflict) or (
            error is None and "terminated by other getupdates" in record.getMessage().lower()
        ):
            _handle_conflict()
            return False  # swallow the original noisy record
        return True


def install_conflict_filter() -> None:
    """Attach :class:`ConflictLogFilter` to the loggers PTB polls with.

    Safe to call more than once; startup behaviour is otherwise unchanged.
    """
    for name in ("telegram.ext.Updater", "telegram.ext._updater", "telegram.ext.Application"):
        target = logging.getLogger(name)
        if not any(isinstance(f, ConflictLogFilter) for f in target.filters):
            target.addFilter(ConflictLogFilter())


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error

    # Only one getUpdates consumer is allowed per bot token. This is not a bug
    # in a handler, so it never reaches a user — just log it once and let
    # polling keep retrying.
    if isinstance(error, Conflict):
        _handle_conflict()
        return

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
