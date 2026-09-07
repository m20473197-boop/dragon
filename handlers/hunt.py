"""Handler for the شکار (hunt) command."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from config import HUNT_PREY
from game import actions
from game.eggs import egg_display
from utils.text import format_remaining, to_fa


async def hunt_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    player_repo = context.bot_data["player_repo"]
    egg_service = context.bot_data["egg_service"]

    player, created = player_repo.get_or_create(user.id, user.username)
    result = actions.hunt(player_repo, player)

    if not result.success:
        await message.reply_text(
            "⏳ هنوز از شکار قبلی برنگشتی و خسته‌ای!\n\n"
            f"⌛ تا شکار بعدی {format_remaining(result.cooldown_remaining)} صبر کن."
        )
        return

    prey = HUNT_PREY[result.prey_key]
    lines = [
        "🏹 شکار موفق!",
        "",
        f"{prey['emoji']} یک {prey['name']} شکار کردی",
        "",
        f"🥩 {to_fa(result.meat_gained)} گوشت دریافت کردی",
    ]
    if created:
        lines.append("")
        lines.append("🐉 به بازی اژدها خوش اومدی!")

    if result.egg_found:
        egg = egg_service.create_found_egg(update.effective_chat.id, user.id)
        emoji, name = egg_display(egg.egg_type)
        lines.append("")
        lines.append(f"{emoji} یک <b>{name}</b> هم پیدا کردی و تخم رو برداشتی!")
        await message.reply_html("\n".join(lines))
        return

    await message.reply_text("\n".join(lines))
