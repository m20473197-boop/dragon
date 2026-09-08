"""Dragon Management System — «اژدها های من».

A selection-first interface for players who own several dragons:

1. «اژدها های من» lists the player's dragons as inline buttons (one per
   dragon, labelled with its type emoji and name).
2. Pressing a button edits the message into that dragon's profile page and
   marks that dragon as the user's *active* dragon.
3. The profile page offers 🥩 غذا دادن / ⬆️ ارتقا / ✏️ تغییر نام / 🔙 برگشت,
   all bound to the selected dragon id.
4. 🔙 برگشت edits the message back to the selection list.

Feeding lives **only** here — there is no feeding command at all: the food
menu offers «🥩 یک غذا بده» (one unit) and «🍖 سیرش کن» (fill up, consuming
only what is needed).

Safety: the selected dragon id travels inside the callback data and every
action re-loads the dragon with :meth:`DragonRepository.get_owned`, so a
button can only ever affect a dragon the presser actually owns — no other
dragon (or player) can be modified by accident or on purpose.
"""
from __future__ import annotations

import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from config import FOODS, HUNGER_LOW_THRESHOLD, UPGRADES
from game.dragons import current_hunger, dragon_type_display, effective_power
from handlers.name_dragon import start_naming_for_dragon
from utils.text import to_fa

logger = logging.getLogger(__name__)

# Callback data namespace: "dg:<action>[:<dragon_id>[:<extra>]]".
PREFIX = "dg:"
ACTION_LIST = "list"
ACTION_VIEW = "view"
ACTION_FEED = "feed"          # dg:feed:<dragon_id>        -> feeding menu
ACTION_EAT_ONE = "eat1"       # dg:eat1:<dragon_id>        -> one food unit
ACTION_EAT_FULL = "eatfull"   # dg:eatfull:<dragon_id>     -> feed until full
ACTION_UPGRADE = "up"         # dg:up:<dragon_id>          -> upgrade menu
ACTION_UPGRADE_DO = "updo"    # dg:updo:<dragon_id>:<key>  -> apply upgrade
ACTION_RENAME = "rename"

SELECT_TITLE = "🐉 اژدهای خود را انتخاب کنید:"
NO_DRAGONS_TEXT = (
    "🐉 هنوز اژدهایی نداری!\n"
    "تخم اژدهاها رو توی گروه پیدا کن و ازشون نگهداری کن؛ وقتی زمانش برسه "
    "اژدهای خودت از تخم بیرون میاد. 🥚"
)
FULL_TEXT = "🐉 اژدهای تو سیر است!"


# --- keyboards --------------------------------------------------------------
def selection_keyboard(dragons, active_id: int | None = None) -> InlineKeyboardMarkup:
    """One button per dragon: «<emoji> <name>» -> dg:view:<id>.

    The active dragon is marked with a ✅ so the user can see the current
    selection at a glance.
    """
    rows = []
    for dragon in dragons:
        emoji, _ = dragon_type_display(dragon.dragon_type)
        mark = " ✅" if active_id is not None and dragon.id == active_id else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{emoji} {dragon.name}{mark}",
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


def feed_keyboard(dragon_id: int) -> InlineKeyboardMarkup:
    """The feeding menu for one specific dragon."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🥩 یک غذا بده",
                    callback_data=f"{PREFIX}{ACTION_EAT_ONE}:{dragon_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🍖 سیرش کن",
                    callback_data=f"{PREFIX}{ACTION_EAT_FULL}:{dragon_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 برگشت", callback_data=f"{PREFIX}{ACTION_VIEW}:{dragon_id}"
                )
            ],
        ]
    )


def upgrade_keyboard(dragon_id: int) -> InlineKeyboardMarkup:
    """One button per configured upgrade, plus back to the profile."""
    rows = [
        [
            InlineKeyboardButton(
                f"{spec['emoji']} {spec['name']}",
                callback_data=f"{PREFIX}{ACTION_UPGRADE_DO}:{dragon_id}:{key}",
            )
        ]
        for key, spec in UPGRADES.items()
    ]
    rows.append(
        [InlineKeyboardButton("🔙 برگشت", callback_data=f"{PREFIX}{ACTION_VIEW}:{dragon_id}")]
    )
    return InlineKeyboardMarkup(rows)


# --- texts ------------------------------------------------------------------
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


def feed_menu_text(dragon, meat: int, fish: int, now: float | None = None) -> str:
    hunger = current_hunger(dragon, now if now is not None else time.time())
    return "\n".join(
        [
            f"🥩 غذا دادن به {dragon.name}",
            "",
            f"🍖 سیری فعلی: {to_fa(hunger)}٪",
            "",
            "❄️ سردخانه:",
            f"🥩 گوشت: {to_fa(meat)}",
            f"🐟 ماهی: {to_fa(fish)}",
        ]
    )


def upgrade_menu_text(dragon, meat: int, fish: int) -> str:
    lines = [
        f"⬆️ ارتقای «{dragon.name}»",
        "",
        f"⭐ سطح: {to_fa(dragon.level)}   ❤️ سلامت: {to_fa(dragon.max_hp)}   "
        f"🔥 قدرت: {to_fa(dragon.power)}",
        "",
        "هزینه‌ی ارتقاها از سردخانه پرداخت می‌شه:",
    ]
    for spec in UPGRADES.values():
        cost = "، ".join(
            f"{to_fa(amount)} {FOODS[res]['name']}" for res, amount in spec["cost"].items()
        )
        lines.append(f"{spec['emoji']} {spec['name']} (+{to_fa(spec['amount'])}) — {cost}")
    lines += ["", f"❄️ موجودی: 🥩 {to_fa(meat)} | 🐟 {to_fa(fish)}"]
    return "\n".join(lines)


def _food_report(spent: dict) -> str:
    """«۳ گوشت و ۲ ماهی مصرف شد.» from a {food_key: units} mapping."""
    parts = [
        f"{FOODS[key]['emoji']} {to_fa(units)} {FOODS[key]['name']}"
        for key, units in spent.items()
        if units
    ]
    return " و ".join(parts)


# --- command ----------------------------------------------------------------
async def my_dragons_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«اژدها های من» — show the dragon selection list."""
    user = update.effective_user
    message = update.effective_message
    players = context.bot_data["player_repo"]
    players.get_or_create(user.id, user.username)
    dragons = _owned_dragons(context, user.id)

    if not dragons:
        await message.reply_text(NO_DRAGONS_TEXT)
        return

    active_id = players.get_active_dragon_id(user.id)
    await message.reply_text(
        SELECT_TITLE, reply_markup=selection_keyboard(dragons, active_id)
    )


# --- callbacks --------------------------------------------------------------
async def dragon_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route every «dg:» button press."""
    query = update.callback_query
    if query is None or query.from_user is None or query.from_user.is_bot:
        return

    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    user_id = query.from_user.id

    try:
        if action == ACTION_LIST:
            await _show_list(query, context, user_id)
            return

        dragon_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        dragon = _owned_dragon(context, dragon_id, user_id)
        if dragon is None:
            await _answer(query, "این اژدها مال تو نیست.", alert=True)
            return

        if action == ACTION_VIEW:
            # Selecting a dragon also makes it the user's active dragon.
            context.bot_data["player_repo"].set_active_dragon(user_id, dragon.id)
            await _answer(query)
            await _edit(query, profile_text(dragon), profile_keyboard(dragon.id))
        elif action == ACTION_FEED:
            await _show_feed_menu(query, context, dragon, user_id)
        elif action == ACTION_EAT_ONE:
            await _feed_one(query, context, dragon, user_id)
        elif action == ACTION_EAT_FULL:
            await _feed_full(query, context, dragon, user_id)
        elif action == ACTION_UPGRADE:
            await _show_upgrades(query, context, dragon, user_id)
        elif action == ACTION_UPGRADE_DO:
            await _apply_upgrade(query, context, dragon, user_id, parts[3] if len(parts) > 3 else "")
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
    active_id = context.bot_data["player_repo"].get_active_dragon_id(user_id)
    await _edit(query, SELECT_TITLE, selection_keyboard(dragons, active_id))


async def _show_feed_menu(query, context, dragon, user_id: int) -> None:
    meat, fish = _storage(context, user_id)
    await _answer(query)
    await _edit(
        query, feed_menu_text(dragon, meat, fish), feed_keyboard(dragon.id)
    )


async def _feed_one(query, context, dragon, user_id: int) -> None:
    """🥩 یک غذا بده — consume exactly one food unit."""
    result = context.bot_data["feeding_service"].feed_unit(user_id, dragon.id)
    if not result.success:
        await _feed_failure(query, context, dragon, user_id, result.reason)
        return

    lines = [
        f"🐉 {result.dragon.name} غذا خورد!",
        "",
        f"{FOODS[result.food_key]['emoji']} ۱ {FOODS[result.food_key]['name']} مصرف شد.",
        "",
        "🍖 Hunger:",
        f"{to_fa(result.hunger_before)}٪ → {to_fa(result.hunger_after)}٪",
    ]
    if result.hp_healed > 0:
        lines.append(f"❤️ سلامت +{to_fa(result.hp_healed)}")
    if result.xp_added > 0:
        lines.append(f"✨ تجربه +{to_fa(result.xp_added)}")
    if result.levels_gained > 0:
        lines.append(f"🎉 Level Up! سطح {to_fa(result.dragon.level)}")

    meat, fish = _storage(context, user_id)
    lines += ["", f"❄️ سردخانه: 🥩 {to_fa(meat)} | 🐟 {to_fa(fish)}"]

    await _answer(query)
    await _edit(query, "\n".join(lines), feed_keyboard(result.dragon.id))


async def _feed_full(query, context, dragon, user_id: int) -> None:
    """🍖 سیرش کن — consume only as much food as the dragon needs."""
    result = context.bot_data["feeding_service"].feed_until_full(user_id, dragon.id)
    if not result.success:
        await _feed_failure(query, context, dragon, user_id, result.reason)
        return

    lines = [
        f"🐉 {result.dragon.name} سیر شد!",
        "",
        f"{_food_report(result.spent)} مصرف شد.",
        "",
        "🍖 Hunger:",
        f"{to_fa(result.hunger_before)}٪ → {to_fa(result.hunger_after)}٪",
    ]
    if result.hunger_after < 100:
        lines.append("")
        lines.append("❄️ سردخانه خالی شد؛ بیشتر از این نشد سیرش کرد.")
    if result.hp_healed > 0:
        lines.append(f"❤️ سلامت +{to_fa(result.hp_healed)}")
    if result.xp_added > 0:
        lines.append(f"✨ تجربه +{to_fa(result.xp_added)}")
    if result.levels_gained > 0:
        lines.append(f"🎉 Level Up! سطح {to_fa(result.dragon.level)}")

    meat, fish = _storage(context, user_id)
    lines += ["", f"❄️ سردخانه: 🥩 {to_fa(meat)} | 🐟 {to_fa(fish)}"]

    await _answer(query)
    await _edit(query, "\n".join(lines), feed_keyboard(result.dragon.id))


async def _feed_failure(query, context, dragon, user_id: int, reason: str) -> None:
    if reason == "full":
        await _answer(query, FULL_TEXT, alert=True)
        return
    if reason == "no_food":
        await _answer(
            query,
            "❄️ سردخانه‌ات خالیه! با «شکار» و «ماهیگیری» غذا جمع کن.",
            alert=True,
        )
        return
    await _answer(query, "این اژدها مال تو نیست.", alert=True)


async def _show_upgrades(query, context, dragon, user_id: int) -> None:
    meat, fish = _storage(context, user_id)
    await _answer(query)
    await _edit(
        query, upgrade_menu_text(dragon, meat, fish), upgrade_keyboard(dragon.id)
    )


async def _apply_upgrade(query, context, dragon, user_id: int, key: str) -> None:
    if key not in UPGRADES:
        await _answer(query)
        return

    result = context.bot_data["upgrade_service"].apply(user_id, dragon.id, key)
    if not result.success:
        if result.reason == "not_enough":
            need = "، ".join(
                f"{to_fa(amount)} {FOODS[res]['name']}"
                for res, amount in result.missing.items()
            )
            await _answer(query, f"❄️ کافی نداری! هنوز {need} لازمه.", alert=True)
        else:
            await _answer(query, "این اژدها مال تو نیست.", alert=True)
        return

    spec = UPGRADES[key]
    gains = "، ".join(
        {
            "max_hp": f"❤️ حداکثر سلامت +{to_fa(v)}",
            "power": f"🔥 قدرت +{to_fa(v)}",
            "level": f"⭐ سطح +{to_fa(v)}",
        }[stat]
        for stat, v in result.gains.items()
    )
    cost = "، ".join(
        f"{FOODS[res]['emoji']} {to_fa(amount)} {FOODS[res]['name']}"
        for res, amount in result.spent.items()
    )
    lines = [
        f"{spec['emoji']} «{result.dragon.name}» ارتقا پیدا کرد!",
        "",
        gains,
        f"💸 هزینه: {cost}",
        "",
        profile_text(result.dragon),
    ]
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


def _storage(context, user_id: int) -> tuple[int, int]:
    """Current (meat, fish) in the user's cold storage."""
    contents = context.bot_data["storage_service"].contents(user_id)
    return contents.meat, contents.fish


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
