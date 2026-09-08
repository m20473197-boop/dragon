"""Scheduled background jobs: egg spawning, hatching and expiry.

* ``spawn_tick``  — periodically rolls for a new egg in every active group,
  respecting a per-group spawn cooldown (``config.EGG_SPAWN_INTERVAL``).
* ``chest_tick``  — periodically rolls for a random chest in every active
  group, and expires chests nobody opened in time.
* ``hatch_sweep`` — periodically hatches due eggs and expires stale unclaimed
  ones, announcing results in the group.

Expired eggs and chests are *deleted* from the group (not merely stripped of
their button) and removed from play, so nothing stays around permanently.

Each per-chat / per-egg step is isolated in its own try/except so a single
failure (e.g. the bot was removed from one group) never aborts the whole sweep.
"""
from __future__ import annotations

import html
import logging
import random

from telegram.ext import ContextTypes

from config import (
    CHEST_ACTIVE_WINDOW_SECONDS,
    CHEST_CHANCE_PER_CHECK,
    SPAWN_ACTIVE_WINDOW_SECONDS,
    SPAWN_CHANCE_PER_CHECK,
)
from game import spawn_settings
from game.eggs import dragon_display, egg_display
from handlers.chests import CHEST_TEXT, build_chest_keyboard, safe_send_message
from handlers.cleanup import delete_message
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
            if random.random() >= SPAWN_CHANCE_PER_CHECK:
                continue

            # Per-group cooldown: at most one egg per EGG_SPAWN_INTERVAL.
            # The claim is a guarded UPDATE, so simultaneous ticks cannot both
            # spawn, and the timestamp is stored so the timer survives a
            # restart. Each group has its own independent timer.
            if not chats_repo.try_claim_egg_spawn(
                chat.chat_id, spawn_settings.get_interval()
            ):
                continue

            # Groups that already have an unclaimed egg are skipped atomically.
            egg = egg_service.spawn_wild_egg(chat.chat_id)
            if egg is None:
                # Nothing spawned after all — give the slot back so the group
                # is not silently locked out for a whole interval.
                chats_repo.release_egg_spawn(chat.chat_id, chat.last_egg_spawn_time)
                continue
            # Bot removed from group / timeout — the egg row exists but has no
            # message; the cooldown still applies so the bot does not hammer a
            # group it cannot post in.
            sent = await safe_send_message(
                context,
                chat.chat_id,
                SPAWN_TEXT,
                what="egg announcement",
                reply_markup=build_spawn_keyboard(egg.id),
            )
            if sent is None:
                logger.warning("Could not spawn egg in chat %s", chat.chat_id)
            else:
                egg_service.eggs.set_message_id(egg.id, sent.message_id)
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
        "🐣 تخم باز شد!\n\n"
        f"{egg_emoji} {egg_name} ➜ {emoji} <b>{dragon_name}</b>\n"
        f"👤 {owner_link}"
    )
    sent = await safe_send_message(
        context, event.chat_id, text, what="hatch announcement", parse_mode="HTML"
    )
    if sent is None:
        logger.warning("Could not announce hatching in chat %s", event.chat_id)


async def _sweep_expired_egg(context: ContextTypes.DEFAULT_TYPE, egg: Egg) -> None:
    """Delete the message of an egg nobody collected in time.

    The egg row is already marked expired by the service, so the egg is out of
    play; here we only remove its now-dead message from the group.
    """
    if not egg.message_id:
        return
    egg_service = context.bot_data["egg_service"]
    try:
        await delete_message(context, egg.chat_id, egg.message_id)
        egg_service.eggs.clear_message(egg.id)
    except Exception:
        logger.exception("Could not delete expired egg %s message", egg.id)


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
        await _sweep_expired_egg(context, egg)


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
                sent = await safe_send_message(
                    context,
                    chat.chat_id,
                    CHEST_TEXT,
                    what="chest announcement",
                    reply_markup=build_chest_keyboard(chest.id),
                )
                if sent is None:
                    logger.warning(
                        "Chest %s announcement failed in chat %s; it will expire quietly",
                        chest.id, chat.chat_id,
                    )
                else:
                    chest_service.chests.set_message_id(chest.id, sent.message_id)
            except Exception:
                logger.exception("Could not spawn chest in chat %s", chat.chat_id)
        except Exception:
            logger.exception("chest_tick: failed for chat %s", chat.chat_id)

    # Chests nobody opened are removed from play and their message deleted,
    # so a chest never stays in the group permanently.
    try:
        expired = chest_service.expire_stale_chests()
    except Exception:
        logger.exception("chest_tick: error while expiring chests")
        expired = []

    for chest in expired:
        if not chest.message_id:
            continue
        try:
            await delete_message(context, chest.group_id, chest.message_id)
            chest_service.chests.clear_message(chest.id)
        except Exception:
            logger.exception("Could not delete expired chest %s message", chest.id)
