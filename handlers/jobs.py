"""Scheduled background jobs: egg spawning, hatching and expiry.

* ``spawn_tick``  — periodically rolls for a new egg in every active group.
* ``chest_tick``  — periodically rolls for a random chest in every active
  group, and expires chests nobody opened in time.
* ``hatch_sweep`` — periodically hatches due eggs and expires stale unclaimed
  ones, announcing results in the group.

Each per-chat / per-egg step is isolated in its own try/except so a single
failure (e.g. the bot was removed from one group) never aborts the whole sweep.
"""
from __future__ import annotations

import html
import logging
import random

from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from config import (
    CHEST_ACTIVE_WINDOW_SECONDS,
    CHEST_CHANCE_PER_CHECK,
    SPAWN_ACTIVE_WINDOW_SECONDS,
    SPAWN_CHANCE_PER_CHECK,
)
from game.eggs import dragon_display, egg_display
from handlers.chests import CHEST_TEXT, build_chest_keyboard
from handlers.spawn import SPAWN_TEXT, build_spawn_keyboard
from models.egg import Egg
from models.player import PlayerRepository

logger = logging.getLogger(__name__)


def _repos(context: ContextTypes.DEFAULT_TYPE):
    return context.bot_data["chat_repo"], context.bot_data["egg_service"]


async def spawn_tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Try to spawn an egg in each active group."""
    chats_repo, egg_service = _repos(context)
    try:
        active = chats_repo.active_chats(SPAWN_ACTIVE_WINDOW_SECONDS)
    except Exception:
        logger.exception("spawn_tick: could not load active chats")
        return

    for chat in active:
        try:
            # Groups that already have an unclaimed egg are skipped atomically.
            if random.random() >= SPAWN_CHANCE_PER_CHECK:
                continue
            egg = egg_service.spawn_wild_egg(chat.chat_id)
            if egg is None:
                continue
            try:
                sent = await context.bot.send_message(
                    chat_id=chat.chat_id,
                    text=SPAWN_TEXT,
                    reply_markup=build_spawn_keyboard(egg.id),
                )
                egg_service.eggs.set_message_id(egg.id, sent.message_id)
            except (BadRequest, TelegramError):
                # Bot removed from group / cannot post — skip it.
                logger.warning("Could not spawn egg in chat %s", chat.chat_id, exc_info=True)
        except Exception:
            logger.exception("spawn_tick: failed for chat %s", chat.chat_id)


async def _announce_hatching(context: ContextTypes.DEFAULT_TYPE, event) -> None:
    players: PlayerRepository = context.bot_data["player_repo"]
    emoji, dragon_name = dragon_display(event.dragon.dragon_type)
    egg_emoji, egg_name = egg_display(event.egg.egg_type)

    try:
        owner = players.get(event.owner_id)
    except Exception:
        owner = None

    if owner is not None and owner.username:
        owner_link = (
            f"<a href='https://t.me/{html.escape(owner.username)}'>"
            f"@{html.escape(owner.username)}</a>"
        )
    else:
        owner_link = f"<a href='tg://user?id={event.owner_id}'>کاربر</a>"

    text = (
        f"🐉 تخم {egg_emoji} <b>{egg_name}</b> شکست!\n"
        f"{owner_link} صاحب یک {emoji} <b>{dragon_name}</b> شد! تبریک! 🎉"
    )
    try:
        await context.bot.send_message(chat_id=event.chat_id, text=text, parse_mode="HTML")
    except (BadRequest, TelegramError):
        logger.warning("Could not announce hatching in chat %s", event.chat_id, exc_info=True)


async def _sweep_expired_button(context: ContextTypes.DEFAULT_TYPE, egg: Egg) -> None:
    """Remove the claim button from an expired egg's spawn message."""
    if not egg.message_id:
        return
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=egg.chat_id, message_id=egg.message_id, reply_markup=None
        )
    except (BadRequest, TelegramError):
        pass  # message deleted / too old / not found — ignore
    except Exception:
        logger.debug("Unexpected error hiding expired button", exc_info=True)


async def hatch_sweep(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hatch due eggs and expire stale unclaimed ones."""
    _, egg_service = _repos(context)

    try:
        events = egg_service.process_hatchings()
    except Exception:
        logger.exception("hatch_sweep: error while processing hatchings")
        events = []

    for event in events:
        try:
            await _announce_hatching(context, event)
        except Exception:
            logger.exception("hatch_sweep: could not announce hatching of egg %s", event.egg.id)

    try:
        expired = egg_service.expire_stale_eggs()
    except Exception:
        logger.exception("hatch_sweep: error while expiring stale eggs")
        expired = []

    for egg in expired:
        await _sweep_expired_button(context, egg)


async def chest_tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Try to spawn a random chest in each active group, and expire old ones."""
    chats_repo = context.bot_data["chat_repo"]
    chest_service = context.bot_data["chest_service"]

    try:
        active = chats_repo.active_chats(CHEST_ACTIVE_WINDOW_SECONDS)
    except Exception:
        logger.exception("chest_tick: could not load active chats")
        active = []

    for chat in active:
        try:
            if random.random() >= CHEST_CHANCE_PER_CHECK:
                continue
            # Groups that already have an unopened chest are skipped atomically.
            chest = chest_service.spawn_chest(chat.chat_id)
            if chest is None:
                continue
            try:
                sent = await context.bot.send_message(
                    chat_id=chat.chat_id,
                    text=CHEST_TEXT,
                    reply_markup=build_chest_keyboard(chest.id),
                )
                chest_service.chests.set_message_id(chest.id, sent.message_id)
            except (BadRequest, TelegramError):
                logger.warning("Could not spawn chest in chat %s", chat.chat_id, exc_info=True)
        except Exception:
            logger.exception("chest_tick: failed for chat %s", chat.chat_id)

    # Clean up chests nobody opened: drop their buttons so they look closed.
    try:
        expired = chest_service.expire_stale_chests()
    except Exception:
        logger.exception("chest_tick: error while expiring chests")
        expired = []

    for chest in expired:
        if not chest.message_id:
            continue
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chest.group_id, message_id=chest.message_id, reply_markup=None
            )
        except (BadRequest, TelegramError):
            pass
        except Exception:
            logger.debug("Unexpected error hiding expired chest button", exc_info=True)
