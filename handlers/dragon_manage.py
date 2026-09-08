"""Dragon Management System — «اژدها های من».

A selection-first interface for players who own several dragons:

1. «اژدها های من» lists the player's dragons as inline buttons (one per
   dragon, labelled with its type emoji and name).
2. Pressing a button edits the message into that dragon's profile page.
3. The profile page offers 🥩 غذا دادن / ⬆️ ارتقا / ✏️ تغییر نام / 🔙 برگشت,
   all bound to the *selected* dragon id.
4. 🔙 برگشت edits the message back to the selection list.

Safety: the selected dragon id travels inside the callback data and every
action re-loads the dragon with :meth:`DragonRepository.get_owned`, so a
button can only ever affect a dragon the presser actually owns — no other
dragon (or player) can be modified by accident or on purpose.

This module only adds an interface; the underlying dragon, feeding, XP and
naming systems are the existing ones and stay untouched.
"""
from __future__ import annotations

import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from config import FOODS, HUNGER_LOW_THRESHOLD
from game.dragons import current_hunger, dragon_type_display, effective_power
from handlers.name_dragon import start_naming_for_dragon
from utils.text import to_fa

logger = logging.getLogger(__name__)

# Callback data namespace: "dg:<action>[:<dragon_id>[:<extra>]]".
PREFIX = "dg:"
ACTION_LIST = "list"
ACTION_VIEW = "view"
ACTION_FEED = "feed"
ACTION_EAT = "eat"        # dg:eat:<dragon_id>:<food_key>
ACTION_UPGRADE = "up"
ACTION_RENAME = "rename"

SELECT_TITLE = "🐉 اژدهای خود را انتخاب کنید:"
NO_DRAGONS_TEXT = (
    "🐉 هنوز اژدهایی نداری!\n"
    "تخم اژدهاها رو توی گروه پیدا کن و ازشون نگهداری کن؛ وقتی زمانش برسه "
    "اژدهای خودت از تخم بیرون میاد. 🥚"
)


# --- keyboards --------------------------------------------------------------
def selection_keyboard(dragons) -> InlineKeyboardMarkup:
    """One button per dragon: «<emoji> <name>» -> dg:view:<id>."""
    rows = []
    for dragon in dragons:
        emoji, _ = dragon_type_display(dragon.dragon_type)
        rows.append(
            [
                InlineKeyboardButton(
                    f"{emoji} {dragon.name}",
                    callback_data=f"{PREFIX}{ACTION_VIEW}:{dragon.id}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def profile_keyboard(dragon_id: int) -> InlineKeyboardMarkup:
    """Management buttons, each carrying the selected dragon's id."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🥩 غذا دادن", callback_data=f"{PREFIX}{ACTION_FEED}:{dragon_id}"
                ),
                InlineKeyboardButton(
                    "⬆️ ارتقا", callback_data=f"{PREFIX}{ACTION_UPGRADE}:{dragon_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "✏️ تغییر نام", callback_data=f"{PREFIX}{ACTION_RENAME}:{dragon_id}"
                ),
                InlineKeyboardButton(
                    "🔙 برگشت", callback_data=f"{PREFIX}{ACTION_LIST}"
                ),
            ],
        ]
    )


def food_keyboard(dragon_id: int, meat: int, fish: int) -> InlineKeyboardMarkup:
    """Food choices for one specific dragon, plus a way back to its profile."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"🥩 گوشت ({to_fa(meat)}) — هزینه {to_fa(FOODS['meat']['cost'])}",
                    callback_data=f"{PREFIX}{ACTION_EAT}:{dragon_id}:meat",
                )
            ],
            [
                InlineKeyboardButton(
                    f"🐟 ماهی ({to_fa(fish)}) — هزینه {to_fa(FOODS['fish']['cost'])}",
                    callback_data=f"{PREFIX}{ACTION_EAT}:{dragon_id}:fish",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 برگشت", callback_data=f"{PREFIX}{ACTION_VIEW}:{dragon_id}"
                )
            ],
        ]
    )


# --- profile text -----------------------------------------------------------
def profile_text(dragon, now: float | None = None) -> str:
    """Render the dragon profile page."""
    now = now if now is not None else time.time()
    emoji, type_name = dragon_type_display(dragon.dragon_type)
    hunger = current_hunger(dragon, now)
    power = effective_power(dragon.power, hunger)

    if hunger < HUNGER_LOW_THRESHOLD:
        hunger_line = f"🍖 سیری: {to_fa(hunger)}٪ (گرسنه!)"
        power_line = f"🔥 قدرت: {to_fa(power)} (از {to_fa(dragon.power)})"
    else:
        hunger_line = f"🍖 سیری: {to_fa(hunger)}٪"
        power_line = f"🔥 قدرت: {to_fa(dragon.power)}"

    return "\n".join(
        [
            "🐉 مشخصات اژدها",
            "",
            f"📛 نام: {dragon.name}",
            f"{emoji} نوع: {type_name}",
            "",
            f"⭐ سطح: {to_fa(dragon.level)}",
            f"✨ تجربه: {to_fa(dragon.xp)} / {to_fa(dragon.xp_required_for_next_level())}",
            "",
            f"❤️ سلامت: {to_fa(dragon.hp)} / {to_fa(dragon.max_hp)}",
            power_line,
            "",
            hunger_line,
        ]
    )


def upgrade_text(dragon) -> str:
    """Explain the dragon's progress toward its next level (no new mechanic)."""
    needed = dragon.xp_required_for_next_level()
    remaining = max(0, needed - dragon.xp)
    return "\n".join(
        [
            f"⬆️ ارتقای اژدهای «{dragon.name}»",
            "",
            f"⭐ سطح فعلی: {to_fa(dragon.level)}",
            f"✨ تجربه: {to_fa(dragon.xp)} / {to_fa(needed)}",
            f"📈 تا سطح بعدی: {to_fa(remaining)} تجربه",
            "",
            "راه‌های گرفتن تجربه:",
            f"🥩 غذا دادن (گوشت +{to_fa(FOODS['meat']['xp'])} / ماهی +{to_fa(FOODS['fish']['xp'])})",
            "🏹 شکار و 🎣 ماهیگیری",
            "",
            "با هر سطح، سلامت و قدرت اژدها بیشتر می‌شه.",
        ]
    )


# --- command ----------------------------------------------------------------
async def my_dragons_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«اژدها های من» — show the dragon selection list."""
    user = update.effective_user
    message = update.effective_message
    context.bot_data["player_repo"].get_or_create(user.id, user.username)
    dragons = _owned_dragons(context, user.id)

    if not dragons:
        await message.reply_text(NO_DRAGONS_TEXT)
        return

    await message.reply_text(SELECT_TITLE, reply_markup=selection_keyboard(dragons))


# --- callbacks --------------------------------------------------------------
async def dragon_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route every «dg:» button press."""
    query = update.callback_query
    if query is None or query.from_user is None or query.from_user.is_bot:
        return

    parts = (query.data or "").split(":")
    # parts[0] == "dg"
    action = parts[1] if len(parts) > 1 else ""
    user_id = query.from_user.id

    try:
        if action == ACTION_LIST:
            await _show_list(query, context, user_id)
            return

        dragon_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        dragon = _owned_dragon(context, dragon_id, user_id)
        if dragon is None:
            # Not the presser's dragon (or it no longer exists).
            await _answer(query, "این اژدها مال تو نیست.", alert=True)
            return

        if action == ACTION_VIEW:
            await _answer(query)
            await _edit(query, profile_text(dragon), profile_keyboard(dragon.id))
        elif action == ACTION_FEED:
            await _show_food(query, context, dragon, user_id)
        elif action == ACTION_EAT:
            food_key = parts[3] if len(parts) > 3 else ""
            await _feed(query, context, dragon, user_id, food_key)
        elif action == ACTION_UPGRADE:
            await _answer(query)
            await _edit(query, upgrade_text(dragon), profile_keyboard(dragon.id))
        elif action == ACTION_RENAME:
            await _start_rename(query, context, dragon)
        else:
            await _answer(query)
    except (BadRequest, TelegramError):
        logger.debug("Dragon management callback failed", exc_info=True)
        await _answer(query)


async def _show_list(query, context, user_id: int) -> None:
    dragons = _owned_dragons(context, user_id)
    await _answer(query)
    if not dragons:
        await _edit(query, NO_DRAGONS_TEXT, None)
        return
    await _edit(query, SELECT_TITLE, selection_keyboard(dragons))


async def _show_food(query, context, dragon, user_id: int) -> None:
    player = context.bot_data["player_repo"].get(user_id)
    meat = player.meat if player else 0
    fish = player.fish if player else 0
    await _answer(query)
    text = (
        f"🍖 غذا دادن به «{dragon.name}»\n\n"
        f"🥩 گوشت موجود: {to_fa(meat)}\n"
        f"🐟 ماهی موجود: {to_fa(fish)}\n\n"
        "یک غذا انتخاب کن:"
    )
    await _edit(query, text, food_keyboard(dragon.id, meat, fish))


async def _feed(query, context, dragon, user_id: int, food_key: str) -> None:
    if food_key not in FOODS:
        await _answer(query)
        return

    # dragon_id is passed explicitly so only the selected dragon is fed.
    result = context.bot_data["feeding_service"].feed(
        user_id, food_key, dragon_id=dragon.id
    )
    if not result.success:
        food = FOODS[food_key]
        if result.reason == "no_dragon":
            await _answer(query, "این اژدها مال تو نیست.", alert=True)
        else:
            await _answer(
                query,
                f"{food['emoji']} {food['name']} کافی نداری! با شکار/ماهیگیری تهیه کن.",
                alert=True,
            )
        return

    food = FOODS[food_key]
    lines = [f"{food['emoji']} {food['name']} رو به «{result.dragon.name}» دادی!", ""]
    if result.hp_healed > 0:
        lines.append(f"❤️ سلامت +{to_fa(result.hp_healed)}")
    lines.append(f"✨ تجربه +{to_fa(result.xp_added)}")
    lines.append(f"🍖 سیری: {to_fa(result.hunger_after)}٪")
    if result.levels_gained > 0:
        lines.append("")
        lines.append(f"🎉 Level Up! سطح {to_fa(result.dragon.level)}")
    lines.append("")
    lines.append(profile_text(result.dragon))

    await _answer(query)
    await _edit(query, "\n".join(lines), profile_keyboard(result.dragon.id))


async def _start_rename(query, context, dragon) -> None:
    """Open the existing naming prompt, bound to the selected dragon."""
    chat = query.message.chat if query.message is not None else None
    if chat is None:
        await _answer(query)
        return
    start_naming_for_dragon(
        context, user_id=query.from_user.id, dragon_id=dragon.id, chat_id=chat.id
    )
    await _answer(query)
    await _edit(
        query,
        f"✏️ نام تازه‌ی «{dragon.name}» رو بفرست.\n\n"
        "برای لغو، یکی از دستورهای بازی رو بفرست.",
        profile_keyboard(dragon.id),
    )


# --- helpers ----------------------------------------------------------------
def _owned_dragons(context, user_id: int):
    """The user's dragons, oldest first (stable button order)."""
    dragons = context.bot_data["dragon_service"].list_for_owner(user_id)
    return list(reversed(dragons))


def _owned_dragon(context, dragon_id: int, user_id: int):
    """Load a dragon only if the presser owns it."""
    if dragon_id <= 0:
        return None
    return context.bot_data["dragon_repo"].get_owned(dragon_id, user_id)


async def _edit(query, text: str, markup: InlineKeyboardMarkup | None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except (BadRequest, TelegramError):
        logger.debug("Could not edit dragon management message", exc_info=True)


async def _answer(query, text: str | None = None, alert: bool = False) -> None:
    try:
        await query.answer(text, show_alert=alert)
    except (BadRequest, TelegramError):
        pass
