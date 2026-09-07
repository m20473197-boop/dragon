"""Helpers for recording group activity (used by the egg spawner)."""
from __future__ import annotations

import logging

from telegram import Chat, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def track_chat(chat: Chat | None, context: ContextTypes.DEFAULT_TYPE | None = None) -> None:
    """Record activity in a group so the spawner knows it is active.

    Only groups/supergroups are tracked (no private chats). Best-effort: a
    database error is logged and swallowed so it can never break command
    handling.
    """
    if chat is None or chat.type not in ("group", "supergroup"):
        return
    try:
        if context is not None and "chat_repo" in context.bot_data:
            repo = context.bot_data["chat_repo"]
        else:
            # Fallback (e.g. used very early); repositories are stateless.
            from models.chat import ChatRepository

            repo = ChatRepository()
        repo.touch(chat.id, chat.title)
    except Exception:
        logger.warning("Failed to track chat %s", chat.id, exc_info=True)


def track_from_update(update: Update, context: ContextTypes.DEFAULT_TYPE | None = None) -> None:
    track_chat(update.effective_chat, context)
