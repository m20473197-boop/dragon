"""Handler for the شکار (hunt) command."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from config import HUNT_PREY, HUNT_XP
from game import actions
from game.eggs import egg_display
from handlers.growth import award_and_announce
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
            f"⏳ خسته‌ای!\n\n⌛ {format_remaining(result.cooldown_remaining)}"
        )
        return

    prey = HUNT_PREY[result.prey_key]
    lines = [
        "🏹 شکار موفق!",
        "",
        f"{prey['emoji']} {prey['name']}",
        f"🥩 +{to_fa(result.meat_gained)}",
    ]
    if created:
        lines.append("")
        lines.append("🐉 خوش اومدی!")

    if result.egg_found:
        egg = egg_service.create_found_egg(update.effective_chat.id, user.id)
        emoji, name = egg_display(egg.egg_type)
        lines.append("")
        lines.append(f"{emoji} <b>{name}</b> هم پیدا کردی!")
        await message.reply_html("\n".join(lines))
    else:
        await message.reply_text("\n".join(lines))

    # Gathering gives the owner's newest dragon XP (level-ups are announced).
    await award_and_announce(context, update.effective_chat.id, user.id, HUNT_XP)
