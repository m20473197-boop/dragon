"""Handler for the ماهیگیری (fishing) command."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from game import actions
from game.eggs import egg_display
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
            "⏳ قلاب ماهیگیری‌ات هنوز آماده نیست!\n\n"
            f"⌛ {format_remaining(result.cooldown_remaining)} دیگه صبر کن."
        )
        return

    lines = [
        "🎣 ماهیگیری موفق!",
        "",
        f"🐟 {to_fa(result.fish_gained)} ماهی گرفتی",
    ]
    if created:
        lines.append("")
        lines.append("🐉 به بازی اژدها خوش اومدی!")

    if result.egg_found:
        egg = egg_service.create_found_egg(update.effective_chat.id, user.id)
        emoji, name = egg_display(egg.egg_type)
        lines.append("")
        lines.append(f"{emoji} توی تورت یک <b>{name}</b> هم بود! مال تو شد و در حال پرورشه.")
        await message.reply_html("\n".join(lines))
        return

    await message.reply_text("\n".join(lines))
