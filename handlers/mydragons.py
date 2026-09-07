"""Handler for the اژدهای من (my dragons) command.

Shows the player's dragons with name, type, level, xp, hp and power. No
combat/PvP here — this is the dragon management/inspection view.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from game.dragons import dragon_type_display
from utils.text import to_fa


def _format_dragon(dragon, index: int, total: int) -> list[str]:
    emoji, type_name = dragon_type_display(dragon.dragon_type)
    lines: list[str] = []
    # A heading per dragon when the player owns several.
    if total > 1:
        lines.append(f"🐲 اژدهای {to_fa(index)}")
        lines.append("")
    lines.extend(
        [
            "🐉 اژدهای من",
            "",
            f"📛 نام: {dragon.name}",
            f"{emoji} نوع: {type_name}",
            f"⭐ سطح: {to_fa(dragon.level)}",
            f"✨ تجربه: {to_fa(dragon.xp)}",
            f"❤️ سلامت: {to_fa(dragon.hp)} / {to_fa(dragon.max_hp)}",
            f"🔥 قدرت: {to_fa(dragon.power)}",
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
