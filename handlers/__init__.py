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
    COMMAND_ADMIN_PANEL,
    COMMAND_ADMIN_TEST_EGG,
    COMMAND_BATTLE,
    COMMAND_EGGS,
    COMMAND_FISHING,
    COMMAND_HUNT,
    COMMAND_MARKET,
    COMMAND_MY_DRAGONS_MENU,
    COMMAND_NAME_DRAGON,
    COMMAND_STORAGE,
    COMMAND_TREASURY,
    CLEANUP_SWEEP_INTERVAL_SECONDS,
    CHEST_CHECK_INTERVAL_SECONDS,
    HATCH_SWEEP_INTERVAL_SECONDS,
    SPAWN_CHECK_INTERVAL_SECONDS,
)
from game.combat import CombatService
from game.dragons import DragonService
from game.eggs import EggService
from game.feeding import FeedingService
from game.chests import ChestService
from game.market import MarketService
from game.storage import ColdStorageService
from game.treasury import TreasuryService
from game.upgrades import UpgradeService
from handlers.battle import (
    PREFIX as BATTLE_PREFIX,
    battle_callback,
    battle_command,
)
from handlers.common import help_command, start_command
from handlers.eggs import eggs_command
from handlers.errors import on_error
from handlers.fishing import fishing_command
from handlers.hunt import hunt_command
from handlers.chests import CHEST_PREFIX, open_chest_callback
from handlers.cleanup import cleanup_tick
from handlers.jobs import chest_tick, hatch_sweep, spawn_tick
from handlers.market import (
    PREFIX as MARKET_PREFIX,
    market_callback,
    market_command,
)
from admin import keyboards as admin_kb
from admin.handlers import admin_capture, admin_callback, admin_panel_command, admin_test_egg_command
from handlers.dragon_manage import (
    PREFIX as DRAGON_MANAGE_PREFIX,
    dragon_manage_callback,
    my_dragons_menu_command,
)
from handlers.name_dragon import (
    cancel_naming_prompt,
    capture_dragon_name,
    name_dragon_command,
)
from handlers.spawn import CLAIM_PREFIX, claim_callback
from handlers.storage import storage_command
from handlers.treasury import (
    PREFIX as TREASURY_PREFIX,
    treasury_callback,
    treasury_command,
)
from handlers.tracking import track_from_update
from admin.service import AdminService
from models.battle import BattleRepository
from models.chat import ChatRepository
from models.chest import ChestRepository
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
    COMMAND_MY_DRAGONS_MENU: my_dragons_menu_command,
    COMMAND_NAME_DRAGON: name_dragon_command,
    COMMAND_STORAGE: storage_command,
    COMMAND_MARKET: market_command,
    COMMAND_TREASURY: treasury_command,
    COMMAND_BATTLE: battle_command,
    COMMAND_ADMIN_PANEL: admin_panel_command,
    COMMAND_ADMIN_TEST_EGG: admin_test_egg_command,
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

    # Admin multiline shortcuts (e.g. "اضافه غذا / گوشت / 100") and pending
    # admin flows take precedence for admins.
    if await admin_capture(update, context):
        return

    # If this message is a known game command, it runs normally and cancels any
    # open naming prompt (handled inside the capture). Otherwise, if the user is
    # mid "نام اژدها" flow, the message is treated as the dragon name.
    if text in COMMAND_MAP:
        # A real game command runs normally and abandons any open naming
        # prompt, so the command's flow is not treated as a dragon name.
        cancel_naming_prompt(context)
        handler = COMMAND_MAP[text]
        await handler(update, context)
        return

    await capture_dragon_name(update, context)


def _setup_shared_objects(application: Application) -> None:
    """Create repositories/services once and share them via bot_data."""
    application.bot_data["player_repo"] = PlayerRepository()
    application.bot_data["chat_repo"] = ChatRepository()
    application.bot_data["egg_repo"] = EggRepository()
    application.bot_data["chest_repo"] = ChestRepository()
    application.bot_data["dragon_repo"] = DragonRepository()
    application.bot_data["battle_repo"] = BattleRepository()

    # Cold storage (سردخانه) holds every player's meat and fish. It is shared
    # by gathering (deposit) and feeding (consume).
    application.bot_data["storage_service"] = ColdStorageService(
        players=application.bot_data["player_repo"]
    )
    application.bot_data["dragon_service"] = DragonService(
        dragons=application.bot_data["dragon_repo"]
    )
    application.bot_data["feeding_service"] = FeedingService(
        dragons=application.bot_data["dragon_repo"],
        players=application.bot_data["player_repo"],
        storage=application.bot_data["storage_service"],
    )
    application.bot_data["egg_service"] = EggService(
        eggs=application.bot_data["egg_repo"],
        dragons=application.bot_data["dragon_repo"],
        players=application.bot_data["player_repo"],
        dragon_service=application.bot_data["dragon_service"],
    )
    application.bot_data["chest_service"] = ChestService(
        chests=application.bot_data["chest_repo"],
        players=application.bot_data["player_repo"],
        storage=application.bot_data["storage_service"],
    )
    # Treasury is a read-only view over the systems above (no new storage).
    application.bot_data["treasury_service"] = TreasuryService(
        players=application.bot_data["player_repo"],
        eggs=application.bot_data["egg_repo"],
        storage=application.bot_data["storage_service"],
    )
    application.bot_data["market_service"] = MarketService(
        players=application.bot_data["player_repo"],
        storage=application.bot_data["storage_service"],
        egg_service=application.bot_data["egg_service"],
    )
    # Upgrades are paid in obsidian, so no cold-storage dependency.
    application.bot_data["upgrade_service"] = UpgradeService(
        dragons=application.bot_data["dragon_repo"],
        players=application.bot_data["player_repo"],
    )
    # Basic PvE combat (مبارزه). Rewards reuse the currency + XP systems.
    application.bot_data["combat_service"] = CombatService(
        battles=application.bot_data["battle_repo"],
        dragons=application.bot_data["dragon_repo"],
        players=application.bot_data["player_repo"],
        dragon_service=application.bot_data["dragon_service"],
    )
    application.bot_data["admin_service"] = AdminService(
        players=application.bot_data["player_repo"],
        chats=application.bot_data["chat_repo"],
        eggs=application.bot_data["egg_repo"],
        dragons=application.bot_data["dragon_repo"],
        egg_service=application.bot_data["egg_service"],
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
    jq.run_repeating(chest_tick, interval=CHEST_CHECK_INTERVAL_SECONDS, first=45, name="chest_tick")
    # Deletes expired / already-claimed egg and chest messages. Deadlines are
    # read from the database, so cleanups pending before a restart still run.
    jq.run_repeating(
        cleanup_tick,
        interval=CLEANUP_SWEEP_INTERVAL_SECONDS,
        first=20,
        name="cleanup_tick",
    )
    logger.info(
        "Scheduled egg spawner (every %ss), hatch sweep (every %ss), "
        "chest spawner (every %ss) and message cleanup (every %ss)",
        SPAWN_CHECK_INTERVAL_SECONDS,
        HATCH_SWEEP_INTERVAL_SECONDS,
        CHEST_CHECK_INTERVAL_SECONDS,
        CLEANUP_SWEEP_INTERVAL_SECONDS,
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

    # Inline-button chest opening: "open_chest:<id>"
    application.add_handler(
        CallbackQueryHandler(open_chest_callback, pattern=rf"^{CHEST_PREFIX}\d+$")
    )

    # Market: "mk:<action>[:<category>[:<item>]]"
    application.add_handler(
        CallbackQueryHandler(treasury_callback, pattern=rf"^{TREASURY_PREFIX}")
    )

    application.add_handler(
        CallbackQueryHandler(market_callback, pattern=rf"^{MARKET_PREFIX}")
    )

    # Battle buttons: "bt:<action>:<battle_id>"
    application.add_handler(
        CallbackQueryHandler(battle_callback, pattern=rf"^{BATTLE_PREFIX}")
    )

    # Dragon management panel: "dg:<action>[:<dragon_id>...]"
    application.add_handler(
        CallbackQueryHandler(dragon_manage_callback, pattern=rf"^{DRAGON_MANAGE_PREFIX}")
    )

    # Admin panel callbacks: "admin:..." (handler re-checks permissions).
    application.add_handler(
        CallbackQueryHandler(admin_callback, pattern=rf"^{admin_kb.PREFIX}")
    )

    # Persian word commands (no slash). ~filters.COMMAND ignores "/..." messages.
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_router)
    )

    # Catch-all error handler.
    application.add_error_handler(on_error)

    _setup_jobs(application)
