"""Handler for the سردخانه (cold storage) command.

Shows the player's stored food (meat and fish). The cold storage is where
hunted meat and caught fish are deposited, and from which dragons are fed.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from utils.text import to_fa


async def storage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    player_repo = context.bot_data["player_repo"]
    storage = context.bot_data["storage_service"]

    # Ensure the player exists (their storage starts empty).
    player_repo.get_or_create(user.id, user.username)
    contents = storage.contents(user.id)

    text = (
        "❄️ سردخانه من\n\n"
        f"🥩 گوشت: {to_fa(contents.meat)}\n"
        f"🐟 ماهی: {to_fa(contents.fish)}"
    )
    await message.reply_text(text)
