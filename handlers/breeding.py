"""🧬 آیین پیوند اژدها — the breeding menu and its screens (Version 9).

Entry points: ``/breeding`` (slash) and «پیوند» (Persian word). Both open the
same menu.

Callback data: ``bd:<action>[:<arg>]`` where action is one of ``home``,
``pick1`` / ``pick2`` (open a chooser), ``set1`` / ``set2`` (choose a dragon),
``confirm``, ``status`` or ``close``. The pending selection lives in
``context.user_data`` — it is per-user and temporary, exactly like the
"selected dragon" of the dragon panel, so nothing extra is stored in the DB.

All rules live in :mod:`game.breeding`; this module only renders and reports.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from config import BREEDING_MIN_LEVEL
from game.breeding import (
    REASON_ALREADY_BREEDING,
    REASON_BUSY,
    REASON_LOCK_FAILED,
    REASON_NOT_ENOUGH_AETHER,
    REASON_NOT_ENOUGH_DRAGONS,
    REASON_NOT_OWNED,
    REASON_SAME_DRAGON,
    REASON_TOO_LOW_LEVEL,
    describe_parents,
    pair_cost,
)
from game.rarity import element_label, rarity_display, rarity_label
from utils.text import format_remaining, to_fa

logger = logging.getLogger(__name__)

# Callback namespace (must not collide with dg: / mk: / tr: / ar: / admin: /
# claim_egg: / open_chest:).
PREFIX = "bd:"
ACTION_HOME = "home"
ACTION_PICK1 = "pick1"
ACTION_PICK2 = "pick2"
ACTION_SET1 = "set1"
ACTION_SET2 = "set2"
ACTION_CONFIRM = "confirm"
ACTION_STATUS = "status"
ACTION_CLOSE = "close"

# user_data keys for the pending selection.
KEY_FIRST = "breeding_first"
KEY_SECOND = "breeding_second"

TITLE = "🧬 آیین پیوند اژدها"
SUBTITLE = "دو اژدها رو ترکیب کن تا اژدهای جدید بگیری."

BTN_FIRST = "🐉 انتخاب اژدهای اول"
BTN_SECOND = "🐉 انتخاب اژدهای دوم"
BTN_CONFIRM = "✅ شروع آیین"
BTN_BACK = "🔙 برگشت"
BTN_STATUS = "⏳ وضعیت آیین"

MSG_REQUIREMENTS = "❌ شرایط پیوند کامل نیست!"
MSG_ERROR = "❌ خطا! دوباره بزن."
MSG_PICK_BOTH = "🐉 هر دو اژدها رو انتخاب کن!"
MSG_NO_AETHER = "✨ اتر کافی نداری!"
MSG_BUSY = "⏳ این اژدها درگیر آیینه!"
MSG_ALREADY = "⏳ یه آیین در جریانه!"
MSG_SAME = "🐉 یه اژدها رو دوبار نمی‌شه!"
MSG_LOW_LEVEL = f"⭐ هر دو باید حداقل لِوِل {to_fa(BREEDING_MIN_LEVEL)} باشن!"
MSG_NOT_ENOUGH = "🐉 حداقل ۲ اژدها لازم داری!"

# Failure reason -> short Persian toast.
_REASON_TEXT = {
    REASON_NOT_ENOUGH_DRAGONS: MSG_NOT_ENOUGH,
    REASON_SAME_DRAGON: MSG_SAME,
    REASON_NOT_OWNED: MSG_REQUIREMENTS,
    REASON_TOO_LOW_LEVEL: MSG_LOW_LEVEL,
    REASON_BUSY: MSG_BUSY,
    REASON_ALREADY_BREEDING: MSG_ALREADY,
    REASON_NOT_ENOUGH_AETHER: MSG_NO_AETHER,
    REASON_LOCK_FAILED: MSG_BUSY,
}


# --- keyboards --------------------------------------------------------------
def menu_keyboard(can_confirm: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(BTN_FIRST, callback_data=f"{PREFIX}{ACTION_PICK1}")],
        [InlineKeyboardButton(BTN_SECOND, callback_data=f"{PREFIX}{ACTION_PICK2}")],
    ]
    if can_confirm:
        rows.append(
            [InlineKeyboardButton(BTN_CONFIRM, callback_data=f"{PREFIX}{ACTION_CONFIRM}")]
        )
    rows.append([InlineKeyboardButton(BTN_BACK, callback_data=f"{PREFIX}{ACTION_CLOSE}")])
    return InlineKeyboardMarkup(rows)


def chooser_keyboard(dragons, slot: int, other_id: int | None) -> InlineKeyboardMarkup:
    """One button per selectable dragon for the given slot."""
    action = ACTION_SET1 if slot == 1 else ACTION_SET2
    rows = []
    for dragon in dragons:
        if other_id is not None and dragon.id == other_id:
            continue  # already used in the other slot
        dot, _ = rarity_display(dragon.rarity)
        emoji, _ = element_label(dragon.dragon_type).split(" ", 1)
        mark = "" if dragon.level >= BREEDING_MIN_LEVEL else " ⛔"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{dot} {emoji} {dragon.name} — Lv.{to_fa(dragon.level)}{mark}",
                    callback_data=f"{PREFIX}{action}:{dragon.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(BTN_BACK, callback_data=f"{PREFIX}{ACTION_HOME}")])
    return InlineKeyboardMarkup(rows)


def status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_STATUS, callback_data=f"{PREFIX}{ACTION_STATUS}")],
            [InlineKeyboardButton(BTN_BACK, callback_data=f"{PREFIX}{ACTION_CLOSE}")],
        ]
    )


# --- texts ------------------------------------------------------------------
def _slot_line(label: str, dragon) -> str:
    if dragon is None:
        return f"{label}: —"
    dot, _ = rarity_display(dragon.rarity)
    return f"{label}: {dot} {dragon.name} (Lv.{to_fa(dragon.level)})"


def menu_text(first, second, balance: int) -> str:
    """The breeding home screen."""
    lines = [TITLE, "", SUBTITLE, ""]
    lines.append(_slot_line("۱️⃣", first))
    lines.append(_slot_line("۲️⃣", second))
    lines.append("")
    if first is not None and second is not None:
        cost = pair_cost(first.rarity, second.rarity)
        lines.append(f"💠 هزینه: ✨ {to_fa(cost)}")
    lines.append(f"✨ موجودی: {to_fa(balance)}")
    return "\n".join(lines)


def chooser_text(slot: int, count: int) -> str:
    which = "اول" if slot == 1 else "دوم"
    if count == 0:
        return f"{TITLE}\n\n🐉 اژدهای آزادی نداری!"
    return (
        f"{TITLE}\n\n"
        f"🐉 اژدهای {which} رو انتخاب کن:\n"
        f"⭐ حداقل لِوِل {to_fa(BREEDING_MIN_LEVEL)}"
    )


def started_text(result) -> str:
    """The «ritual started» card."""
    parents = describe_parents([result.parent_a, result.parent_b])
    remaining = result.breeding.remaining()
    return "\n".join(
        [
            "🧬 آیین پیوند شروع شد!",
            "",
            f"🐉 {result.parent_a.name}",
            "+",
            f"🐉 {result.parent_b.name}",
            "",
            f"✨ -{to_fa(result.cost)}   موجودی: ✨ {to_fa(result.balance_after)}",
            "",
            "⏳ زمان باقی‌مانده:",
            format_remaining(remaining),
            "",
            f"🔒 {parents} تا پایان آیین در دسترس نیستن.",
        ]
    )


def status_text(breeding, parent_a, parent_b, now: float | None = None) -> str:
    """The in-progress ritual screen."""
    remaining = breeding.remaining(now)
    names = []
    for dragon in (parent_a, parent_b):
        names.append(f"🐉 {dragon.name}" if dragon is not None else "🐉 ؟")
    return "\n".join(
        [
            "🧬 آیین در جریانه!",
            "",
            names[0],
            "+",
            names[1],
            "",
            "⏳ زمان باقی‌مانده:",
            format_remaining(remaining),
        ]
    )


def result_text(result) -> str:
    """The «ritual complete» card announcing the new dragon."""
    child = result.child
    lines = ["🎉 آیین پیوند موفق بود!", "", "🐉 اژدهای جدید:", "", f"📛 {child.name}"]
    if result.outcome == "hybrid":
        pa, pb = result.parent_a, result.parent_b
        a_emoji, _ = element_display_safe(pa)
        b_emoji, _ = element_display_safe(pb)
        lines.append(f"🔮 عنصر: {a_emoji} + {b_emoji} ➜ {element_label(child.dragon_type)}")
    else:
        lines.append(f"🔮 عنصر: {element_label(child.dragon_type)}")
    lines.append(f"✨ کمیابی: {rarity_label(child.rarity)}")
    lines.append("")
    lines.append(f"❤️ HP: {to_fa(child.max_hp)}")
    lines.append(f"⚔️ قدرت: {to_fa(child.power)}")
    if result.mutated:
        lines.append("")
        lines.append("🧪 جهش! ❤️ +۳۰٪  ⚔️ +۳۰٪")
    return "\n".join(lines)


def element_display_safe(dragon):
    """``(emoji, name)`` for a possibly-missing dragon."""
    from game.rarity import element_display

    if dragon is None:
        return "🐉", "؟"
    return element_display(dragon.dragon_type)


# --- telegram plumbing ------------------------------------------------------
async def _answer(query, text: str | None = None, alert: bool = False) -> None:
    try:
        await query.answer(text=text, show_alert=alert)
    except TelegramError:
        logger.debug("Could not answer breeding callback", exc_info=True)


async def _edit(query, text: str, reply_markup=None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            logger.debug("Breeding edit failed: %s", exc)
    except TelegramError:
        logger.debug("Breeding edit failed", exc_info=True)


def _service(context):
    return context.bot_data.get("breeding_service")


def _selected(context, service, user_id: int):
    """Re-read the pending selection, dropping anything no longer valid."""
    first_id = context.user_data.get(KEY_FIRST)
    second_id = context.user_data.get(KEY_SECOND)
    first = service.dragons.get_owned(first_id, user_id) if first_id else None
    second = service.dragons.get_owned(second_id, user_id) if second_id else None
    if first is None:
        context.user_data.pop(KEY_FIRST, None)
    if second is None:
        context.user_data.pop(KEY_SECOND, None)
    return first, second


async def _render_home(query_or_message, context, service, user_id: int, edit: bool):
    """Show the menu, or the status screen when a ritual is running."""
    active = service.active(user_id)
    if active is not None:
        parent_a = service.dragons.get(active.parent1_id)
        parent_b = service.dragons.get(active.parent2_id)
        text = status_text(active, parent_a, parent_b)
        markup = status_keyboard()
    else:
        first, second = _selected(context, service, user_id)
        text = menu_text(first, second, service.balance(user_id))
        markup = menu_keyboard(can_confirm=first is not None and second is not None)

    if edit:
        await _edit(query_or_message, text, markup)
    else:
        await query_or_message.reply_text(text, reply_markup=markup)


# --- entry points -----------------------------------------------------------
async def breeding_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/breeding`` and «پیوند» — open the breeding menu."""
    user = update.effective_user
    message = update.effective_message
    if user is None or user.is_bot or message is None:
        return

    from handlers.tracking import track_from_update

    track_from_update(update, context)

    service = _service(context)
    players = context.bot_data.get("player_repo")
    if service is None or players is None:
        await message.reply_text(MSG_ERROR)
        return

    try:
        players.get_or_create(user.id, user.username)
        await _render_home(message, context, service, user.id, edit=False)
    except Exception:
        logger.exception("breeding_command failed for user %s", user.id)
        await message.reply_text(MSG_ERROR)


async def breeding_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route ``bd:<action>[:<dragon_id>]`` button presses."""
    query = update.callback_query
    if query is None or query.from_user is None or query.from_user.is_bot:
        return

    data = query.data or ""
    parts = data[len(PREFIX):].split(":") if data.startswith(PREFIX) else []
    action = parts[0] if parts else ""
    arg = parts[1] if len(parts) > 1 else None
    user_id = query.from_user.id

    service = _service(context)
    if service is None:
        await _answer(query, MSG_ERROR, alert=True)
        return

    try:
        if action == ACTION_HOME:
            await _answer(query)
            await _render_home(query, context, service, user_id, edit=True)
        elif action == ACTION_CLOSE:
            await _answer(query)
            context.user_data.pop(KEY_FIRST, None)
            context.user_data.pop(KEY_SECOND, None)
            await _edit(query, f"{TITLE}\n\n🔙 بستیم. هر وقت خواستی «پیوند» بزن.")
        elif action in (ACTION_PICK1, ACTION_PICK2):
            slot = 1 if action == ACTION_PICK1 else 2
            await _handle_pick(query, context, service, user_id, slot)
        elif action in (ACTION_SET1, ACTION_SET2):
            slot = 1 if action == ACTION_SET1 else 2
            await _handle_set(query, context, service, user_id, slot, arg)
        elif action == ACTION_CONFIRM:
            await _handle_confirm(query, context, service, user_id)
        elif action == ACTION_STATUS:
            await _answer(query)
            await _render_home(query, context, service, user_id, edit=True)
        # Unknown actions are ignored (stale buttons).
    except Exception:
        logger.exception("breeding_callback failed (action=%r)", action)
        await _answer(query, MSG_ERROR, alert=True)


async def _handle_pick(query, context, service, user_id: int, slot: int) -> None:
    if service.active(user_id) is not None:
        await _answer(query, MSG_ALREADY, alert=True)
        return
    dragons = service.selectable(user_id)
    other = context.user_data.get(KEY_SECOND if slot == 1 else KEY_FIRST)
    await _answer(query)
    await _edit(
        query,
        chooser_text(slot, len(dragons)),
        chooser_keyboard(dragons, slot, other),
    )


async def _handle_set(query, context, service, user_id: int, slot: int, arg) -> None:
    try:
        dragon_id = int(arg)
    except (TypeError, ValueError):
        await _answer(query, MSG_ERROR, alert=True)
        return

    dragon = service.dragons.get_owned(dragon_id, user_id)
    if dragon is None:
        await _answer(query, MSG_REQUIREMENTS, alert=True)
        return
    if dragon.breeding_status == "breeding":
        await _answer(query, MSG_BUSY, alert=True)
        return
    if dragon.level < BREEDING_MIN_LEVEL:
        await _answer(query, MSG_LOW_LEVEL, alert=True)
        return

    key = KEY_FIRST if slot == 1 else KEY_SECOND
    other_key = KEY_SECOND if slot == 1 else KEY_FIRST
    if context.user_data.get(other_key) == dragon_id:
        await _answer(query, MSG_SAME, alert=True)
        return

    context.user_data[key] = dragon_id
    await _answer(query, f"✅ {dragon.name}")
    await _render_home(query, context, service, user_id, edit=True)


async def _handle_confirm(query, context, service, user_id: int) -> None:
    first_id = context.user_data.get(KEY_FIRST)
    second_id = context.user_data.get(KEY_SECOND)
    if not first_id or not second_id:
        await _answer(query, MSG_PICK_BOTH, alert=True)
        return

    chat_id = query.message.chat_id if query.message is not None else None
    result = service.start(user_id, first_id, second_id, chat_id=chat_id)
    if not result.ok:
        await _answer(query, _REASON_TEXT.get(result.reason, MSG_REQUIREMENTS),
                      alert=True)
        return

    context.user_data.pop(KEY_FIRST, None)
    context.user_data.pop(KEY_SECOND, None)
    await _answer(query, "🧬 شروع شد!")
    await _edit(query, started_text(result), status_keyboard())
