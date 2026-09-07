"""Handler for the اژدهای من (my dragons) command.

Shows the player's dragons with name, type, level, xp, hp and power. No
combat/PvP here — this is the dragon management/inspection view.
"""
from __future__ import annotations

import time

from telegram import Update
from telegram.ext import ContextTypes

from config import HUNGER_LOW_THRESHOLD
from game.dragons import current_hunger, dragon_type_display, effective_power
from utils.text import to_fa


def _format_dragon(dragon, index: int, total: int) -> list[str]:
    emoji, type_name = dragon_type_display(dragon.dragon_type)
    hunger = current_hunger(dragon, time.time())
    power = effective_power(dragon.power, hunger)
    lines: list[str] = []
    # A heading per dragon when the player owns several.
    if total > 1:
        lines.append(f"🐲 اژدهای {to_fa(index)}")
        lines.append("")

    if hunger < HUNGER_LOW_THRESHOLD:
        hunger_line = f"🍗 سیری: {to_fa(hunger)}٪ (گرسنه!)"
        power_line = f"🔥 قدرت: {to_fa(power)} (از {to_fa(dragon.power)}، کم‌شده به خاطر گرسنگی)"
    else:
        hunger_line = f"🍗 سیری: {to_fa(hunger)}٪"
        power_line = f"🔥 قدرت: {to_fa(dragon.power)}"

    lines.extend(
        [
            "🐉 اژدهای من",
            "",
            f"📛 نام: {dragon.name}",
            f"{emoji} نوع: {type_name}",
            f"⭐ سطح: {to_fa(dragon.level)}",
            f"✨ تجربه: {to_fa(dragon.xp)} / {to_fa(dragon.xp_required_for_next_level())}",
            f"❤️ سلامت: {to_fa(dragon.hp)} / {to_fa(dragon.max_hp)}",
            hunger_line,
            power_line,
        ]
    )
    return lines


async def my_dragons_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    player_repo = context.bot_data["player_repo"]
    dragon_service = context.bot_data["dragon_service"]

    # Ensure the player exists (harmless if they already do).
    player_repo.get_or_create(user.id, user.username)

    dragons = dragon_service.list_for_owner(user.id)

    if not dragons:
        await message.reply_text(
            "🐉 هنوز اژدهایی نداری!\n"
            "تخم اژدهاها رو توی گروه پیدا کن و ازشون نگهداری کن؛ وقتی زمانش برسه "
            "اژدهای خودت از تخم بیرون میاد. 🥚"
        )
        return

    blocks: list[str] = []
    total = len(dragons)
    # list_by_owner returns newest first; show oldest (first-hatched) first.
    for position, dragon in enumerate(reversed(dragons), start=1):
        blocks.append("\n".join(_format_dragon(dragon, position, total)))

    separator = "\n\n———————————\n\n" if total > 1 else ""
    await message.reply_text(separator.join(blocks))
