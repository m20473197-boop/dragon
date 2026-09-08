"""Handler for the ماهیگیری (fishing) command."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from config import FISH_XP
from game import actions
from game.eggs import egg_display
from handlers.growth import award_and_announce
from utils.text import format_remaining, to_fa


async def fishing_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    player_repo = context.bot_data["player_repo"]
    egg_service = context.bot_data["egg_service"]

    player, created = player_repo.get_or_create(user.id, user.username)
    result = actions.fish(player_repo, player)

    if not result.success:
        await message.reply_text(
            f"⏳ قلاب آماده نیست!\n\n⌛ {format_remaining(result.cooldown_remaining)}"
        )
        return

    lines = [
        "🎣 ماهیگیری موفق!",
        "",
        f"🐟 +{to_fa(result.fish_gained)} ماهی",
    ]
    if created:
        lines.append("")
        lines.append("🐉 خوش اومدی!")

    if result.egg_found:
        egg = egg_service.create_found_egg(update.effective_chat.id, user.id)
        emoji, _ = egg_display(egg.egg_type)
        lines.append(f"{emoji} تخم اژدها!")
        await message.reply_html("\n".join(lines))
    else:
        await message.reply_text("\n".join(lines))

    # Gathering gives the owner's newest dragon XP (level-ups are announced).
    await award_and_announce(context, update.effective_chat.id, user.id, FISH_XP)
