"""Handler for the غذا بده (feed dragon) command and its food-choice buttons.

The command shows the player's stored meat and fish as two inline buttons.
Pressing one feeds the owner's newest dragon that food (consuming it from
storage), then edits the message with the result so the counts stay fresh.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from config import FOODS
from game.feeding import food_display
from utils.text import to_fa

logger = logging.getLogger(__name__)

# Callback data: "feed:<food_key>".
FEED_PREFIX = "feed:"


def _food_menu(meat: int, fish: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"🥩 گوشت ({to_fa(meat)}) — هزینه {to_fa(FOODS['meat']['cost'])}",
                    callback_data=f"{FEED_PREFIX}meat",
                )
            ],
            [
                InlineKeyboardButton(
                    f"🐟 ماهی ({to_fa(fish)}) — هزینه {to_fa(FOODS['fish']['cost'])}",
                    callback_data=f"{FEED_PREFIX}fish",
                )
            ],
        ]
    )


def _menu_text(meat: int, fish: int) -> str:
    return (
        "🍖 غذا دادن به اژدها\n\n"
        f"🥩 گوشت موجود: {to_fa(meat)}\n"
        f"🐟 ماهی موجود: {to_fa(fish)}\n\n"
        "یک غذا رو برای اژدهات انتخاب کن:"
    )


async def feed_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the player's available food with choice buttons."""
    user = update.effective_user
    message = update.effective_message
    player_repo = context.bot_data["player_repo"]

    player, _ = player_repo.get_or_create(user.id, user.username)
    dragon = context.bot_data["dragon_service"].newest_for_owner(user.id)

    if dragon is None:
        await message.reply_text(
            "🐉 هنوز اژدهایی نداری که بهش غذا بدی!\n"
            "اول یک تخم اژدها بگیر و صبر کن تا اژدها ازش بیرون بیاد. 🥚"
        )
        return

    await message.reply_text(
        _menu_text(player.meat, player.fish),
        reply_markup=_food_menu(player.meat, player.fish),
    )


async def feed_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a press on a meat/fish food button."""
    query = update.callback_query
    if query is None or query.from_user is None or query.from_user.is_bot:
        return

    feeding_service = context.bot_data["feeding_service"]
    player_repo = context.bot_data["player_repo"]

    try:
        food_key = (query.data or "").split(":", 1)[1]
    except IndexError:
        await _answer(query)
        return
    if food_key not in FOODS:
        await _answer(query)
        return

    user = query.from_user
    player_repo.get_or_create(user.id, user.username)
    result = feeding_service.feed(user.id, food_key)

    if not result.success:
        if result.reason == "no_dragon":
            await _answer(query, "🐉 اژدهایی نداری!", alert=True)
        else:
            food = FOODS[food_key]
            await _answer(
                query,
                f"{food['emoji']} {food['name']} کافی نداری! با شکار/ماهیگیری تهیه کن.",
                alert=True,
            )
        return

    emoji, food_name = food_display(food_key)
    d = result.dragon
    lines = [f"{emoji} {food_name} رو به اژدهات دادی!"]
    if result.hp_healed > 0:
        lines.append(f"❤️ سلامت +{to_fa(result.hp_healed)}")
    lines.append(f"✨ تجربه +{to_fa(result.xp_added)}")
    lines.append(f"🍗 سیری: {to_fa(result.hunger_after)}٪")
    if result.levels_gained > 0:
        lines.append("")
        lines.append(f"🎉 اژدهات Level Up شد! سطح {to_fa(d.level)}")

    # Refresh the menu with the new resource counts.
    player = player_repo.get(user.id)
    lines.append("")
    lines.append(f"🥩 گوشت: {to_fa(player.meat)}  |  🐟 ماهی: {to_fa(player.fish)}")
    try:
        await query.answer()
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=_food_menu(player.meat, player.fish),
        )
    except (BadRequest, TelegramError):
        # Message too old / unchanged — post the result instead.
        logger.debug("Could not edit feed message", exc_info=True)
        if query.message is not None:
            try:
                await query.message.reply_text("\n".join(lines))
            except (BadRequest, TelegramError):
                pass


async def _answer(query, text: str | None = None, alert: bool = False) -> None:
    try:
        await query.answer(text, show_alert=alert)
    except (BadRequest, TelegramError):
        pass
