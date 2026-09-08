"""Handler for the سردخانه (cold storage) command.

Shows the player's stored food (meat and fish) plus their currency balances
(🪨 obsidian and ✨ aether). The cold storage is where hunted meat and caught
fish are deposited, and from which dragons are fed.
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

    player = player_repo.get(user.id)
    obsidian = player.obsidian if player else 0
    aether = player.aether if player else 0

    text = (
        "❄️ سردخانه من\n\n"
        f"🥩 گوشت: {to_fa(contents.meat)}\n"
        f"🐟 ماهی: {to_fa(contents.fish)}\n\n"
        "💰 دارایی\n"
        f"🪨 ابسیدین: {to_fa(obsidian)}\n"
        f"✨ اتر: {to_fa(aether)}"
    )
    await message.reply_text(text)
