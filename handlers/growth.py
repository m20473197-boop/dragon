"""Helpers for dragon growth notifications (XP gains / level-ups)."""
from __future__ import annotations

from telegram.ext import ContextTypes

from game.dragons import XpResult, dragon_type_display
from utils.text import to_fa


def build_level_up_text(result: XpResult) -> str:
    """Build the Persian level-up message for every level gained.

    Example output::

        🎉 اژدهای «رخش» Level Up شد!
        ⭐ Level: ۲
        ❤️ +۲۰ Max HP
        🔥 +۵ Power
    """
    blocks: list[str] = []
    emoji, _ = dragon_type_display(result.dragon.dragon_type)
    for event in result.level_ups:
        blocks.append(
            f"🎉 اژدهای «{event.name}» Level Up شد!\n"
            f"{emoji}\n"
            f"⭐ Level: {to_fa(event.new_level)}\n"
            f"❤️ +{to_fa(event.max_hp_gained)} Max HP\n"
            f"🔥 +{to_fa(event.power_gained)} Power"
        )
    return "\n\n".join(blocks)


async def award_and_announce(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    owner_id: int,
    xp: int,
) -> None:
    """Give ``xp`` to the owner's newest dragon and announce any level-ups.

    Best-effort: failures are logged in the service layer and never block the
    gathering response.
    """
    if xp <= 0:
        return
    dragon_service = context.bot_data["dragon_service"]
    dragon = dragon_service.newest_for_owner(owner_id)
    if dragon is None:
        return  # no dragon yet; the owner has no one to earn XP

    result = dragon_service.add_xp(dragon.id, xp)
    if result is not None and result.leveled_up:
        text = build_level_up_text(result)
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception:  # noqa: BLE001 - announcement is non-critical
            pass
