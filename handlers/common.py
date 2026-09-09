"""Handlers for /start and /help."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from config import (
    COMMAND_EGGS,
    COMMAND_FISHING,
    COMMAND_HUNT,
    COMMAND_MARKET,
    COMMAND_MY_DRAGONS_MENU,
    COMMAND_NAME_DRAGON,
    COMMAND_STORAGE,
    COMMAND_TREASURY,
    COMMAND_BREEDING,
)
from handlers.keyboards import main_menu_keyboard
from handlers.tracking import track_from_update

WELCOME_TEXT = (
    "🐉 بازی اژدها\n\n"
    "🥚 تخم بگیر → 🐲 اژدها پرورش بده → ⚔️ بجنگ!\n\n"
    "📜 دستورها:\n"
    f"🏹 {COMMAND_HUNT}\n"
    f"🎣 {COMMAND_FISHING}\n"
    f"🥚 {COMMAND_EGGS}\n"
    f"🐉 {COMMAND_MY_DRAGONS_MENU}\n"
    f"📛 {COMMAND_NAME_DRAGON}\n"
    f"❄️ {COMMAND_STORAGE}\n"
    f"🏪 {COMMAND_MARKET}\n"
    f"🏰 {COMMAND_TREASURY}\n"
    f"🧬 {COMMAND_BREEDING}\n"
    "🏟️ /arena"
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_from_update(update, context)
    # The reply keyboard is an accessibility shortcut: every button sends the
    # very same Persian word the user could type by hand.
    await update.effective_message.reply_text(
        WELCOME_TEXT, reply_markup=main_menu_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_from_update(update, context)
    await update.effective_message.reply_text(
        WELCOME_TEXT, reply_markup=main_menu_keyboard()
    )
