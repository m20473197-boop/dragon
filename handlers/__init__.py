"""Telegram handlers and their registration.

Slash-commands (``/start``, ``/help``) use CommandHandler; the Persian word
commands (شکار، ماهیگیری، تخم ها — typed *without* a slash) are routed through
a single MessageHandler. The inline-button claim uses CallbackQueryHandler,
and the egg spawner/hatcher run as scheduled jobs.

To add a new Persian command: add the word to ``config.py`` and the map
below, then create a handler module — no other wiring needed.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    COMMAND_EGGS,
    COMMAND_FISHING,
    COMMAND_HUNT,
    COMMAND_MY_DRAGONS,
    HATCH_SWEEP_INTERVAL_SECONDS,
    SPAWN_CHECK_INTERVAL_SECONDS,
)
from game.dragons import DragonService
from game.eggs import EggService
from handlers.common import help_command, start_command
from handlers.eggs import eggs_command
from handlers.errors import on_error
from handlers.fishing import fishing_command
from handlers.hunt import hunt_command
from handlers.jobs import hatch_sweep, spawn_tick
from handlers.mydragons import my_dragons_command
from handlers.spawn import CLAIM_PREFIX, claim_callback
from handlers.tracking import track_from_update
from models.chat import ChatRepository
from models.dragon import DragonRepository
from models.egg import EggRepository
from models.player import PlayerRepository
from utils.text import normalize_command

logger = logging.getLogger(__name__)

# Persian trigger word -> handler coroutine
COMMAND_MAP = {
    COMMAND_HUNT: hunt_command,
    COMMAND_FISHING: fishing_command,
    COMMAND_EGGS: eggs_command,
    COMMAND_MY_DRAGONS: my_dragons_command,
}


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route plain-text messages that exactly match a Persian command."""
    if update.effective_user is None or update.effective_user.is_bot:
        return

    # Every group message counts as activity for the spawner (best-effort).
    track_from_update(update, context)

    message = update.effective_message
    if message is None or not message.text:
        return
    text = normalize_command(message.text)

    handler = COMMAND_MAP.get(text)
    if handler is not None:
        await handler(update, context)


def _setup_shared_objects(application: Application) -> None:
    """Create repositories/services once and share them via bot_data."""
    application.bot_data["player_repo"] = PlayerRepository()
    application.bot_data["chat_repo"] = ChatRepository()
    application.bot_data["egg_repo"] = EggRepository()
    application.bot_data["dragon_repo"] = DragonRepository()
    application.bot_data["dragon_service"] = DragonService(
        dragons=application.bot_data["dragon_repo"]
    )
    application.bot_data["egg_service"] = EggService(
        eggs=application.bot_data["egg_repo"],
        dragons=application.bot_data["dragon_repo"],
        players=application.bot_data["player_repo"],
        dragon_service=application.bot_data["dragon_service"],
    )


def _setup_jobs(application: Application) -> None:
    jq = application.job_queue
    if jq is None:
        logger.warning(
            "JobQueue unavailable (install 'python-telegram-bot[job-queue]'). "
            "Eggs will not spawn or hatch automatically."
        )
        return
    jq.run_repeating(spawn_tick, interval=SPAWN_CHECK_INTERVAL_SECONDS, first=10, name="spawn_tick")
    jq.run_repeating(hatch_sweep, interval=HATCH_SWEEP_INTERVAL_SECONDS, first=15, name="hatch_sweep")
    logger.info(
        "Scheduled egg spawner (every %ss) and hatch sweep (every %ss)",
        SPAWN_CHECK_INTERVAL_SECONDS,
        HATCH_SWEEP_INTERVAL_SECONDS,
    )


def register_all(application: Application) -> None:
    """Attach every handler and start background jobs."""
    _setup_shared_objects(application)

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    # Inline-button claim: "claim_egg:<id>"
    application.add_handler(
        CallbackQueryHandler(claim_callback, pattern=rf"^{CLAIM_PREFIX}\d+$")
    )

    # Persian word commands (no slash). ~filters.COMMAND ignores "/..." messages.
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_router)
    )

    # Catch-all error handler.
    application.add_error_handler(on_error)

    _setup_jobs(application)
