"""Dragon Management System — «اژدها».

A selection-first interface for players who own several dragons:

1. «اژدها» lists the player's dragons as inline buttons (one per
   dragon, labelled with its type emoji and name).
2. Pressing a button edits the message into that dragon's profile page. This
   only *selects* the dragon for viewing — it does **not** change the user's
   active dragon.
3. The profile page offers ⭐ انتخاب به عنوان فعال / 🥩 غذا دادن / ⬆️ ارتقا /
   ✏️ تغییر نام / 🔙 برگشت, all bound to the selected dragon id.
4. 🔙 برگشت edits the message back to the selection list.

Selected vs. active dragon (see :mod:`game.selection`):

* the **selected** dragon is temporary session state and drives viewing,
  feeding, upgrading and renaming — feeding «آذر» feeds only «آذر»;
* the **active** dragon is persisted on the players row and is what the rest
  of the game (combat) uses. It changes **only** through the dedicated
  «⭐ انتخاب به عنوان اژدهای فعال» button.

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
from game.upgrades import LEVEL_UPGRADE_KEY, level_upgrade_cost
from game.dragons import current_hunger, dragon_type_display, effective_power
from game.rarity import element_label, rarity_display, rarity_label
from game.selection import clear_selected_dragon, set_selected_dragon
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
ACTION_SET_ACTIVE = "setactive"  # dg:setactive:<dragon_id> -> make it the active dragon

SELECT_TITLE = "🐉 انتخاب اژدها:"
NO_DRAGONS_TEXT = "🐉 اژدهایی نداری!\n\n🥚 توی گروه تخم پیدا کن."
FULL_TEXT = "🐉 {name} سیره!"
BTN_SET_ACTIVE = "⭐ فعال"
ALREADY_ACTIVE_TEXT = "⭐ همین الان فعاله."


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
        # The rarity dot makes a 🟣/🟡 dragon obvious in the list.
        dot, _name = rarity_display(dragon.rarity)
        rows.append(
            [
                InlineKeyboardButton(
                    f"{dot} {emoji} {dragon.name}{mark}",
                    callback_data=f"{PREFIX}{ACTION_VIEW}:{dragon.id}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def profile_keyboard(dragon_id: int) -> InlineKeyboardMarkup:
    """Management buttons, each carrying the selected dragon's id.

    The first row is the ONLY way to change the active dragon.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🥩 غذا", callback_data=f"{PREFIX}{ACTION_FEED}:{dragon_id}"
                ),
                InlineKeyboardButton(
                    "⬆️ ارتقا", callback_data=f"{PREFIX}{ACTION_UPGRADE}:{dragon_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "✏️ نام", callback_data=f"{PREFIX}{ACTION_RENAME}:{dragon_id}"
                ),
                InlineKeyboardButton(
                    BTN_SET_ACTIVE,
                    callback_data=f"{PREFIX}{ACTION_SET_ACTIVE}:{dragon_id}",
                ),
            ],
            [
                InlineKeyboardButton("🔙", callback_data=f"{PREFIX}{ACTION_LIST}"),
            ],
        ]
    )


def feed_keyboard(dragon_id: int) -> InlineKeyboardMarkup:
    """The feeding menu for one specific dragon."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🥩 یک غذا",
                    callback_data=f"{PREFIX}{ACTION_EAT_ONE}:{dragon_id}",
                ),
                InlineKeyboardButton(
                    "🍖 سیر کن",
                    callback_data=f"{PREFIX}{ACTION_EAT_FULL}:{dragon_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔙", callback_data=f"{PREFIX}{ACTION_VIEW}:{dragon_id}"
                )
            ],
        ]
    )


def _upgrade_price(key: str, spec: dict, dragon_level: int | None) -> int:
    """Price of one upgrade, level-aware for the ⭐ level upgrade."""
    if key == LEVEL_UPGRADE_KEY and dragon_level is not None:
        return level_upgrade_cost(dragon_level)
    return int(spec["cost_obsidian"])


def upgrade_keyboard(dragon_id: int, dragon_level: int | None = None) -> InlineKeyboardMarkup:
    """One button per configured upgrade, plus back to the profile.

    The ⭐ level button shows the progressive price for THIS dragon's current
    level, so the button never advertises a stale cost.
    """
    rows = [
        [
            InlineKeyboardButton(
                f"{spec['emoji']} {spec['short']} 🪨 "
                f"{to_fa(_upgrade_price(key, spec, dragon_level))}",
                callback_data=f"{PREFIX}{ACTION_UPGRADE_DO}:{dragon_id}:{key}",
            )
        ]
        for key, spec in UPGRADES.items()
    ]
    rows.append(
        [InlineKeyboardButton("🔙", callback_data=f"{PREFIX}{ACTION_VIEW}:{dragon_id}")]
    )
    return InlineKeyboardMarkup(rows)


# --- texts ------------------------------------------------------------------
def profile_text(dragon, now: float | None = None, is_active: bool = False) -> str:
    """Compact mobile-game style dragon card.

    Example::

        🐉 آذر 🔥 ⭐

        ⭐ Lv.۵
        ✨ XP: ۲۵۰/۵۰۰

        ❤️ HP: ۱۸۰/۲۰۰
        ⚔️ قدرت: ۴۵
        🍖 گرسنگی: ۷۰٪
    """
    now = now if now is not None else time.time()
    emoji, _ = dragon_type_display(dragon.dragon_type)
    hunger = current_hunger(dragon, now)
    power = effective_power(dragon.power, hunger)

    # A hungry dragon fights weaker — show it inline instead of a paragraph.
    if hunger < HUNGER_LOW_THRESHOLD:
        power_line = f"⚔️ قدرت: {to_fa(power)} ⚠️"
        hunger_line = f"🍖 گرسنگی: {to_fa(hunger)}٪ ⚠️"
    else:
        power_line = f"⚔️ قدرت: {to_fa(dragon.power)}"
        hunger_line = f"🍖 گرسنگی: {to_fa(hunger)}٪"

    star = " ⭐" if is_active else ""
    return "\n".join(
        [
            f"🐉 {dragon.name} {emoji}{star}",
            "",
            f"🔮 عنصر: {element_label(dragon.dragon_type)}",
            f"✨ کمیابی: {rarity_label(dragon.rarity)}",
            *(["🧬 درگیر آیین پیوند"]
              if getattr(dragon, "breeding_status", "idle") == "breeding" else []),
            "",
            f"⭐ Lv.{to_fa(dragon.level)}",
            f"✨ XP: {to_fa(dragon.xp)}/{to_fa(dragon.xp_required_for_next_level())}",
            "",
            f"❤️ HP: {to_fa(dragon.hp)}/{to_fa(dragon.max_hp)}",
            power_line,
            hunger_line,
        ]
    )


def feed_menu_text(dragon, meat: int, fish: int, now: float | None = None) -> str:
    hunger = current_hunger(dragon, now if now is not None else time.time())
    return "\n".join(
        [
            f"🥩 غذا دادن به {dragon.name}",
            "",
            f"🍖 گرسنگی: {to_fa(hunger)}٪",
            "",
            f"🥩 {to_fa(meat)}   🐟 {to_fa(fish)}",
        ]
    )


def upgrade_menu_text(dragon, obsidian: int) -> str:
    """Upgrade card for one dragon; every price is in 🪨 obsidian.

    The ⭐ level price is progressive, so the card always shows what THIS
    dragon's next level actually costs.

    Example::

        ⬆️ ارتقای اژدها

        🐉 آذر
        ⭐ Level: ۵

        ❤️ HP +۲۰ — 🪨 ۵۰۰
        ⚔️ قدرت +۵ — 🪨 ۷۰۰
        ⭐ سطح +۱ — 🪨 ۸۰۰۰

        💰 ۱۲۰۰ 🪨
    """
    lines = [
        "⬆️ ارتقای اژدها",
        "",
        f"🐉 {dragon.name}",
        f"⭐ Level: {to_fa(dragon.level)}",
        "",
    ]
    for key, spec in UPGRADES.items():
        lines.append(
            f"{spec['emoji']} {spec['short']} +{to_fa(spec['amount'])} — "
            f"🪨 {to_fa(_upgrade_price(key, spec, dragon.level))}"
        )
    lines += ["", f"💰 {to_fa(obsidian)} 🪨"]
    return "\n".join(lines)


def _food_report(spent: dict) -> str:
    """«🥩 -۳   🐟 -۲» from a {food_key: units} mapping."""
    parts = [
        f"{FOODS[key]['emoji']} -{to_fa(units)}"
        for key, units in spent.items()
        if units
    ]
    return "   ".join(parts)


# --- command ----------------------------------------------------------------
async def my_dragons_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«اژدها» — show the dragon selection list."""
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
            # Going back to the list drops the temporary selection.
            clear_selected_dragon(getattr(context, "user_data", None))
            await _show_list(query, context, user_id)
            return

        dragon_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        dragon = _owned_dragon(context, dragon_id, user_id)
        if dragon is None:
            await _answer(query, "⛔ مال تو نیست!", alert=True)
            return

        if action == ACTION_VIEW:
            # Viewing only SELECTS the dragon (temporary session state).
            # The active dragon is deliberately left untouched here — it can
            # only be changed with «⭐ انتخاب به عنوان اژدهای فعال».
            await _show_profile(query, context, dragon, user_id)
        elif action == ACTION_SET_ACTIVE:
            await _set_active(query, context, dragon, user_id)
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


async def _show_profile(query, context, dragon, user_id: int) -> None:
    """Open a dragon's page. Selection only — the active dragon is unchanged."""
    set_selected_dragon(getattr(context, "user_data", None), dragon.id)
    active_id = context.bot_data["player_repo"].get_active_dragon_id(user_id)
    await _answer(query)
    await _edit(
        query,
        profile_text(dragon, is_active=(active_id == dragon.id)),
        profile_keyboard(dragon.id),
    )


async def _set_active(query, context, dragon, user_id: int) -> None:
    """«⭐ انتخاب به عنوان اژدهای فعال» — the ONLY way to change it."""
    players = context.bot_data["player_repo"]
    if players.get_active_dragon_id(user_id) == dragon.id:
        await _answer(query, ALREADY_ACTIVE_TEXT, alert=True)
        return

    if not players.set_active_dragon(user_id, dragon.id):
        await _answer(query, "⛔ مال تو نیست!", alert=True)
        return

    await _answer(query, f"⭐ {dragon.name} اکنون اژدهای فعال شماست.", alert=True)
    await _edit(
        query,
        f"⭐ {dragon.name} اکنون اژدهای فعال شماست.\n\n"
        + profile_text(dragon, is_active=True),
        profile_keyboard(dragon.id),
    )


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
        f"{FOODS[result.food_key]['emoji']} {result.dragon.name} غذا خورد!",
        "",
        f"🍖 {to_fa(result.hunger_before)}٪ ➜ {to_fa(result.hunger_after)}٪",
    ]
    extra = []
    if result.hp_healed > 0:
        extra.append(f"❤️ +{to_fa(result.hp_healed)}")
    if result.xp_added > 0:
        extra.append(f"✨ +{to_fa(result.xp_added)}")
    if extra:
        lines.append("   ".join(extra))
    if result.levels_gained > 0:
        lines.append(f"🎉 Lv.{to_fa(result.dragon.level)}!")

    await _answer(query)
    await _edit(query, "\n".join(lines), feed_keyboard(result.dragon.id))


async def _feed_full(query, context, dragon, user_id: int) -> None:
    """🍖 سیرش کن — consume only as much food as the dragon needs."""
    result = context.bot_data["feeding_service"].feed_until_full(user_id, dragon.id)
    if not result.success:
        await _feed_failure(query, context, dragon, user_id, result.reason)
        return

    lines = [
        f"🍖 {result.dragon.name} سیر شد!",
        "",
        f"🍖 {to_fa(result.hunger_before)}٪ ➜ {to_fa(result.hunger_after)}٪",
        _food_report(result.spent),
    ]
    extra = []
    if result.hp_healed > 0:
        extra.append(f"❤️ +{to_fa(result.hp_healed)}")
    if result.xp_added > 0:
        extra.append(f"✨ +{to_fa(result.xp_added)}")
    if extra:
        lines.append("   ".join(extra))
    if result.levels_gained > 0:
        lines.append(f"🎉 Lv.{to_fa(result.dragon.level)}!")
    if result.hunger_after < 100:
        lines.append("❄️ سردخانه خالی شد!")

    await _answer(query)
    await _edit(query, "\n".join(lines), feed_keyboard(result.dragon.id))


async def _feed_failure(query, context, dragon, user_id: int, reason: str) -> None:
    if reason == "full":
        await _answer(query, FULL_TEXT.format(name=dragon.name), alert=True)
        return
    if reason == "no_food":
        await _answer(
            query,
            "❄️ سردخانه خالیه!",
            alert=True,
        )
        return
    await _answer(query, "⛔ مال تو نیست!", alert=True)


async def _show_upgrades(query, context, dragon, user_id: int) -> None:
    balance = context.bot_data["upgrade_service"].balance(user_id)
    await _answer(query)
    await _edit(
        query,
        upgrade_menu_text(dragon, balance),
        upgrade_keyboard(dragon.id, dragon.level),
    )


async def _apply_upgrade(query, context, dragon, user_id: int, key: str) -> None:
    if key not in UPGRADES:
        await _answer(query)
        return

    result = context.bot_data["upgrade_service"].apply(user_id, dragon.id, key)
    if not result.success:
        if result.reason == "not_enough":
            # Short alert, plus the requirement written into the card so the
            # player can see exactly what the upgrade needs.
            await _answer(
                query,
                f"🪨 کم داری! {to_fa(result.missing)} تای دیگه لازمه.",
                alert=True,
            )
            price = _upgrade_price(key, UPGRADES[key], dragon.level)
            await _edit(
                query,
                "\n".join([
                    "❌ ابسیدین کافی نداری!",
                    "",
                    "نیاز:",
                    f"🪨 {to_fa(price)}",
                    "",
                    f"💰 {to_fa(result.balance)} 🪨",
                ]),
                upgrade_keyboard(dragon.id, dragon.level),
            )
            return
        if result.reason == "unknown":
            await _answer(query, "🚧 در دسترس نیست.", alert=True)
        else:
            await _answer(query, "⛔ مال تو نیست!", alert=True)
        return

    gains = "   ".join(
        {
            "max_hp": f"❤️ +{to_fa(v)}",
            "power": f"⚔️ +{to_fa(v)}",
            "level": f"⭐ +{to_fa(v)}",
        }[stat]
        for stat, v in result.gains.items()
    )
    active_id = context.bot_data["player_repo"].get_active_dragon_id(user_id)
    if key == LEVEL_UPGRADE_KEY:
        # A level-up shows the level transition and what the next one costs.
        lines = [
            "⬆️ ارتقا موفق!",
            "",
            "⭐ Level:",
            f"{to_fa(result.previous_level)} ➜ {to_fa(result.dragon.level)}",
            "",
            gains,
            f"🪨 -{to_fa(result.spent)}   💰 {to_fa(result.balance)}",
            "",
            f"⬆️ ارتقای بعدی: 🪨 {to_fa(result.next_cost)}",
        ]
    else:
        lines = [
            "✅ ارتقا شد!",
            "",
            gains,
            f"🪨 -{to_fa(result.spent)}   💰 {to_fa(result.balance)}",
            "",
            profile_text(result.dragon, is_active=(active_id == result.dragon.id)),
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
        f"✏️ نام جدید {dragon.name} رو بفرست:",
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
