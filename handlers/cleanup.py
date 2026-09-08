"""Temporary group messages: deletion deadlines and the cleanup sweep (V5).

Chests and eggs are *temporary*. Two things can happen to their group message:

* nobody claims it  → after ``CHEST_EXPIRE_TIME`` / ``EGG_EXPIRE_TIME`` the
  message is deleted and the reward is removed from play;
* somebody claims it → the message is edited into the result, and deleted
  ``MESSAGE_DELETE_TIME`` later so old messages never pile up.

Timers are **absolute deadlines stored in the database** (``delete_after``),
not in-memory jobs, which is what makes them survive a restart: after a
reboot the sweep simply asks the database which messages are now due. Each
group is swept independently and one failing group never aborts the sweep.
"""
from __future__ import annotations

import logging
import time

from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

from config import MESSAGE_DELETE_TIME

logger = logging.getLogger(__name__)


def deletion_deadline(seconds: float | None = None, now: float | None = None) -> float:
    """Absolute timestamp at which a message should be deleted."""
    now = now if now is not None else time.time()
    return now + (MESSAGE_DELETE_TIME if seconds is None else seconds)


async def delete_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> bool:
    """Delete a group message, treating "already gone" as success.

    Never raises: cleanup runs inside scheduled jobs, and a message the bot
    cannot delete (too old, already removed, missing rights) must not stop the
    rest of the sweep.
    """
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except BadRequest as exc:
        # "message to delete not found" / "message can't be deleted" — the
        # end state we wanted (no message) is reached either way.
        logger.debug("Could not delete message %s in chat %s: %s", message_id, chat_id, exc)
        return True
    except Forbidden as exc:
        logger.warning("Not allowed to delete message %s in chat %s: %s", message_id, chat_id, exc)
    except TelegramError:
        logger.warning(
            "Failed to delete message %s in chat %s", message_id, chat_id, exc_info=True
        )
    except Exception:
        logger.exception("Unexpected error deleting message %s in chat %s", message_id, chat_id)
    return False


async def cleanup_tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete every egg/chest message whose stored deadline has passed.

    Runs on a short interval. Because the deadline is read from the database,
    messages queued before a restart are still cleaned up afterwards.
    """
    now = time.time()
    egg_service = context.bot_data.get("egg_service")
    chest_service = context.bot_data.get("chest_service")

    if egg_service is not None:
        try:
            due_eggs = egg_service.eggs.find_due_deletion(now)
        except Exception:
            logger.exception("cleanup_tick: could not load eggs due for deletion")
            due_eggs = []
        for egg in due_eggs:
            try:
                await delete_message(context, egg.chat_id, egg.message_id)
                # Clear unconditionally: if the message cannot be deleted we
                # must still drop the deadline, or the sweep would retry it
                # forever on every tick.
                egg_service.eggs.clear_message(egg.id)
            except Exception:
                logger.exception("cleanup_tick: failed to clean up egg %s", egg.id)

    if chest_service is not None:
        try:
            due_chests = chest_service.chests.find_due_deletion(now)
        except Exception:
            logger.exception("cleanup_tick: could not load chests due for deletion")
            due_chests = []
        for chest in due_chests:
            try:
                await delete_message(context, chest.group_id, chest.message_id)
                chest_service.chests.clear_message(chest.id)
            except Exception:
                logger.exception("cleanup_tick: failed to clean up chest %s", chest.id)
