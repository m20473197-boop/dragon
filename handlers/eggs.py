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
        lines.append("🐉 به بازی اژدها خوش آمدی!")

    if not eggs:
        lines.append("🥚 تخم فعالی نداری.")
        lines.append("در گروه منتظر پیدا شدن تخم باش یا با شکار و ماهیگیری شانست رو امتحان کن!")
    else:
        lines.append(f"🥚 تخم‌های در حال انکوباسیون ({to_fa(len(eggs))}):")
        now = time.time()
        for egg in eggs:
            emoji, name = egg_display(egg.egg_type)
            remaining = int((egg.hatch_time or now) - now)
            if remaining > 0:
                lines.append(f"{emoji} {name} — ⏳ {format_remaining(remaining)} تا باز شدن")
            else:
                lines.append(f"{emoji} {name} — ✨ هر لحظه ممکنه باز بشه!")

    lines.append("")
    lines.append(f"🐉 اژدها: {to_fa(dragon_count)}")
    lines.append(f"🥩 گوشت: {to_fa(player.meat)}  |  🐟 ماهی: {to_fa(player.fish)}")

    await message.reply_text("\n".join(lines))
