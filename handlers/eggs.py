"""Handler for the تخم ها (my eggs / inventory) command."""
from __future__ import annotations

import time

from telegram import Update
from telegram.ext import ContextTypes

from game.eggs import egg_display
from utils.text import format_remaining, to_fa


async def eggs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    player_repo = context.bot_data["player_repo"]
    egg_service = context.bot_data["egg_service"]

    player, created = player_repo.get_or_create(user.id, user.username)

    eggs = egg_service.eggs.list_active_by_owner(user.id)
    dragon_count = egg_service.dragons.count_by_owner(user.id)

    lines = []
    if created:
        lines.append("🐉 خوش اومدی!")
        lines.append("")

    if not eggs:
        lines.append("🥚 تخمی نداری!")
    else:
        lines.append(f"🥚 تخم‌ها ({to_fa(len(eggs))})")
        lines.append("")
        now = time.time()
        for egg in eggs:
            emoji, _ = egg_display(egg.egg_type)
            remaining = int((egg.hatch_time or now) - now)
            if remaining > 0:
                lines.append(f"{emoji} ⏳ {format_remaining(remaining)}")
            else:
                lines.append(f"{emoji} ✨ الانه که باز شه!")

    lines.append("")
    lines.append(f"🐉 {to_fa(dragon_count)}   🥩 {to_fa(player.meat)}   🐟 {to_fa(player.fish)}")

    await message.reply_text("\n".join(lines))
