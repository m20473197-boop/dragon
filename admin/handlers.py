"""Telegram handlers for the admin panel.

All entry points re-check permissions (``is_admin``) and debug gating
(``can_use_test_tools``) before acting, so the panel is never reachable by
normal users even if a callback data is forged. Multi-step input (adding food,
looking up a user) is captured via :func:`admin_capture`.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from admin import keyboards as kb
from admin.permissions import can_use_test_tools, debug_enabled, is_admin
from admin.service import AdminService
from admin.state import clear_pending, get_pending, set_pending
from config import COMMAND_ADMIN_ADD_FOOD
from utils.text import normalize_command, to_fa

logger = logging.getLogger(__name__)

PANEL_TITLE = "🛠 پنل مدیریت اژدها"
TEST_EGG_TEXT = "🥚 تخم تستی ظاهر شد!"
TEST_CHEST_TEXT = "🎁 صندوق تستی ظاهر شد!"


def _service(context: ContextTypes.DEFAULT_TYPE) -> AdminService:
    return context.bot_data["admin_service"]


def _stats_text(stats: dict) -> str:
    return (
        "📊 آمار بازی\n\n"
        f"👥 کاربران: {to_fa(stats['users'])}\n"
        f"🥚 کل تخم‌ها: {to_fa(stats['eggs'])}\n"
        f"🐉 کل اژدهاها: {to_fa(stats['dragons'])}\n"
        f"💬 گروه‌ها: {to_fa(stats['groups'])}\n"
        f"🏹 کل شکارها: {to_fa(stats['hunts'])}\n"
        f"🎣 کل ماهیگیری‌ها: {to_fa(stats['fishing'])}\n"
        f"🎁 صندوق‌ها: {to_fa(stats['chests'])} "
        f"(باز شده: {to_fa(stats['chests_opened'])})\n"
        f"🪨 کل ابسیدین: {to_fa(stats['obsidian'])}\n"
        f"✨ کل اتر: {to_fa(stats['aether'])}"
    )


def _user_info_text(info) -> str:
    lines = [
        "👤 اطلاعات کاربر",
        "",
        f"🆔 شناسه: <code>{to_fa(info.user_id)}</code>",
        f"🔖 یوزرنیم: @{info.username or '—'}",
        f"🥚 تخم‌ها: {to_fa(info.eggs)}",
        f"🐉 اژدهاها: {to_fa(info.dragons)}",
        f"🥩 گوشت: {to_fa(info.meat)}",
        f"🐟 ماهی: {to_fa(info.fish)}",
        f"🪨 ابسیدین: {to_fa(info.obsidian)}",
        f"✨ اتر: {to_fa(info.aether)}",
        f"🏹 شکار: {to_fa(info.hunt_count)}",
        f"🎣 ماهیگیری: {to_fa(info.fishing_count)}",
        "",
        "🐲 اژدهاها:",
    ]
    if not info.dragons_list:
        lines.append("  —")
    for d in info.dragons_list:
        lines.append(
            f"  • {d.name} | سطح {to_fa(d.level)} | XP {to_fa(d.xp)} "
            f"| HP {to_fa(d.hp)}/{to_fa(d.max_hp)} | قدرت {to_fa(d.power)}"
        )
    return "\n".join(lines)


async def _spawn_test_chest(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, send_to: int | None = None
):
    """Spawn an admin test chest and post it with the normal open button."""
    # Imported lazily to avoid a circular import (handlers <-> admin packages).
    from handlers.chests import build_chest_keyboard

    service = _service(context)
    chest = service.spawn_test_chest(chat_id)
    if chest is None:
        return None
    try:
        sent = await context.bot.send_message(
            chat_id=send_to or chat_id,
            text=TEST_CHEST_TEXT,
            reply_markup=build_chest_keyboard(chest.id),
        )
        service.chests.set_message_id(chest.id, sent.message_id)
    except (BadRequest, TelegramError):
        logger.warning("Admin test chest: could not send message to %s", chat_id, exc_info=True)
    return chest


# --- entry command ----------------------------------------------------------
async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        return  # silently ignore non-admins (command is unknown to them)
    clear_pending(context)
    msg = PANEL_TITLE
    if not debug_enabled():
        msg += "\n\n🔧 حالت تست خاموش است؛ فقط ابزارهای مانیتورینگ فعال‌اند."
    await update.effective_message.reply_text(msg, reply_markup=kb.panel_keyboard())


# --- test egg ---------------------------------------------------------------
async def admin_test_egg_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Text command «ساخت تخم تست» -> spawn a test egg in the current group."""
    user = update.effective_user
    if not can_use_test_tools(user.id):
        return
    chat = update.effective_chat
    if chat is None or chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("این دستور فقط داخل گروه کار می‌کنه.")
        return
    await _spawn_test_egg(context, chat.id, send_to=chat.id)


async def _spawn_test_egg(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, send_to: int | None = None
):
    # Imported lazily to avoid a circular import (handlers <-> admin packages).
    from handlers.spawn import build_spawn_keyboard

    service = _service(context)
    egg = service.spawn_test_egg(chat_id)
    if egg is None:
        return None
    try:
        sent = await context.bot.send_message(
            chat_id=send_to or chat_id,
            text=TEST_EGG_TEXT,
            reply_markup=build_spawn_keyboard(egg.id),
        )
        service.eggs.set_message_id(egg.id, sent.message_id)
    except (BadRequest, TelegramError):
        logger.warning("Admin test egg: could not send message to %s", chat_id, exc_info=True)
    return egg


# --- callbacks --------------------------------------------------------------
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None:
        return
    user_id = query.from_user.id
    if not is_admin(user_id):
        await _answer(query, "دسترسی نداری.", alert=True)
        return

    payload = (query.data or "")[len(kb.PREFIX):]
    action = payload.split(":", 1)[0]
    arg = payload.split(":", 1)[1] if ":" in payload else None
    service = _service(context)

    try:
        if action == kb.CB_BACK:
            clear_pending(context)
            await _safe_edit(query, PANEL_TITLE, kb.panel_keyboard())
            await _answer(query)
            return

        # Monitoring tools (admin only, debug-independent).
        if action == kb.CB_STATS:
            await _safe_edit(query, _stats_text(service.game_stats()), kb.panel_keyboard())
            await _answer(query)
            return

        if action == kb.CB_USER_INFO:
            set_pending(context, "user_info", {})
            await _safe_edit(query, "👤 برای اطلاعات کاربر، روی پیامش ریپلای کن و «اطلاعات کاربر» رو بفرست، یا شناسه عددی کاربر رو بفرست.")
            await _answer(query)
            return

        # Everything below is a testing tool -> requires debug mode.
        if not debug_enabled():
            await _answer(query, "ابزار تست در حالت تولید غیرفعال است.", alert=True)
            return

        if action == kb.CB_TEST_EGG:
            chat_id = query.message.chat_id if query.message else user_id
            await _spawn_test_egg(context, chat_id)
            await _answer(query, "🥚 تخم تست ساخته شد.")
            return

        if action == kb.CB_TEST_CHEST:
            chat_id = query.message.chat_id if query.message else user_id
            await _spawn_test_chest(context, chat_id)
            await _answer(query, "🎁 صندوق تست ساخته شد.")
            return

        if action == kb.CB_TEST_DRAGON:
            await _create_test_dragon_for(query, context)
            return

        if action == kb.CB_ADD_FOOD:
            await _handle_add_food(query, context, arg)
            return

        if action == kb.CB_HATCH:
            if arg is None:
                await _safe_edit(query, "⏩ زمان خروج اژدها از تخم (تستی):", kb.hatch_keyboard())
                await _answer(query)
            else:
                seconds = int(arg)
                if seconds > 0:
                    service.set_hatch_override(seconds)
                    text = f"✅ زمان تخم تستی: {to_fa(seconds)} ثانیه"
                else:
                    service.set_hatch_override(None)
                    text = "✅ زمان تخم به حالت پیش‌فرض برگشت."
                await _safe_edit(query, text, kb.panel_keyboard())
                await _answer(query)
            return

        if action == kb.CB_RESET:
            await _safe_edit(
                query,
                "🗑 مطمئنی؟ فقط تخم/اژدها/صندوق *تستی* ساخته‌شده توسط ادمین پاک می‌شن.\n"
                "داده‌های واقعی کاربران دست‌نخورده باقی می‌مونه.",
                kb.reset_confirm_keyboard(),
            )
            await _answer(query)
            return

        if action == kb.CB_RESET_CONFIRM:
            result = service.reset_test_data()
            clear_pending(context)
            text = (
                f"✅ پاک‌سازی انجام شد.\n"
                f"🥚 تخم تستی حذف‌شده: {to_fa(result['eggs'])}\n"
                f"🐉 اژدهای تستی حذف‌شده: {to_fa(result['dragons'])}\n"
                f"🎁 صندوق تستی حذف‌شده: {to_fa(result['chests'])}"
            )
            await _safe_edit(query, text, kb.panel_keyboard())
            await _answer(query)
            return

        await _answer(query)
    except Exception:  # noqa: BLE001 - keep the panel responsive on any failure
        logger.exception("Admin callback failed: %s", payload)
        await _answer(query, "خطایی رخ داد.", alert=True)


async def _create_test_dragon_for(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    service = _service(context)
    # Target the replied-to user if present, else the admin.
    target_id = query.from_user.id
    reply = query.message.reply_to_message
    if reply is not None and reply.from_user is not None and not reply.from_user.is_bot:
        target_id = reply.from_user.id
    dragon = service.create_test_dragon(target_id)
    if dragon is None:
        await query.answer("کاربر در دیتابیس نیست.", show_alert=True)
        return
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=(
            f"🐉 یک اژدهای «{dragon.name}» (سطح {to_fa(dragon.level)}) برای کاربر "
            f"<code>{to_fa(target_id)}</code> ساخته شد."
        ),
        parse_mode="HTML",
    )
    await query.answer("اژدهای تست ساخته شد.")


async def _handle_add_food(query, context: ContextTypes.DEFAULT_TYPE, food_arg: str | None) -> None:
    # Step 1: choose food type (callback admin:add_food with no arg).
    if food_arg is None:
        set_pending(context, "add_food", {"food": None})
        await _safe_edit(query, "🍖 نوع غذا رو انتخاب کن، بعد مقدار رو (با ریپلای به کاربر هدف) بفرست.", kb.food_type_keyboard())
        await query.answer()
        return
    # Step 2: food type chosen -> remember it and ask for amount/target.
    if food_arg in ("meat", "fish"):
        set_pending(context, "add_food", {"food": food_arg})
        await _safe_edit(query, "حالا مقدار را بفرست (مثلاً <b>۱۰۰</b>). برای کاربر دیگری، روی پیامش ریپلای کن.", html=True)
        await query.answer()
        return


# --- text capture for multi-step admin flows -------------------------------
async def admin_capture(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Consume admin text when an admin flow is pending.

    Returns True if the message was handled by the admin flow.
    """
    user = update.effective_user
    if user is None or not is_admin(user.id):
        return False
    pending = get_pending(context)
    if pending is None:
        return False

    message = update.effective_message
    raw = normalize_command(message.text if message else "")
    service = _service(context)

    # Multiline «اضافه غذا / گوشت / 100» shortcut.
    if pending.get("action") != "add_food" and raw.startswith(COMMAND_ADMIN_ADD_FOOD):
        return await _process_add_food_text(update, context, message_text=message.text or "")

    if pending.get("action") == "user_info":
        target_id = _resolve_target_id(update, raw)
        clear_pending(context)
        if target_id is None:
            await message.reply_text("شناسه نامعتبره.")
            return True
        info = service.user_info(target_id)
        if info is None:
            await message.reply_text(f"کاربری با شناسه <code>{to_fa(target_id)}</code> یافت نشد.", parse_mode="HTML")
            return True
        await message.reply_html(_user_info_text(info))
        return True

    if pending.get("action") == "add_food":
        return await _process_add_food_text(
            update,
            context,
            message_text=message.text or "",
            food_override=pending.get("food"),
        )

    clear_pending(context)
    return True


async def _process_add_food_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str, food_override: str | None = None
) -> bool:
    service = _service(context)
    message = update.effective_message

    food_key = food_override
    amount = None
    # Parse either a plain amount, or a 3-line shortcut:
    #   اضافه غذا / گوشت|ماهی / <amount>
    lines = [ln.strip() for ln in message_text.splitlines() if ln.strip()]
    if food_key is None and len(lines) >= 2:
        food_key = _food_from_word(lines[1])
        if len(lines) >= 3:
            amount = _parse_int(lines[2])
    if amount is None:
        amount = _parse_int(lines[-1])
        if food_key is None and len(lines) >= 2:
            food_key = _food_from_word(lines[-2])
    if food_key is None:
        food_key = _food_from_word(message_text)

    target_id = _resolve_target_id(update, message_text)
    if target_id is None:
        await message.reply_text("کاربر هدف مشخص نیست؛ روی پیام کاربر ریپلای کن یا شناسه بفرست.")
        return True
    if food_key not in ("meat", "fish") or amount is None or amount <= 0:
        await message.reply_text(
            "قالب نامعتبر. نمونه:\nاضافه غذا\nگوشت\n100\n\n(یا اول نوع غذا را از دکمه‌ها انتخاب کن، بعد مقدار را بفرست.)"
        )
        return True

    if service.add_food(target_id, food_key, amount):
        clear_pending(context)
        emoji = "🥩" if food_key == "meat" else "🐟"
        word = "گوشت" if food_key == "meat" else "ماهی"
        await message.reply_text(
            f"✅ {to_fa(amount)} {word} به سردخانه کاربر <code>{to_fa(target_id)}</code> اضافه شد. {emoji}",
            parse_mode="HTML",
        )
    else:
        await message.reply_text("کاربر در دیتابیس یافت نشد (اول باید در بازی فعال باشه).")
    return True


# --- helpers ----------------------------------------------------------------
def _food_from_word(text: str) -> str | None:
    t = normalize_command(text)
    if "گوشت" in t:
        return "meat"
    if "ماهی" in t:
        return "fish"
    return None


def _parse_int(text: str) -> int | None:
    # Accept Persian/Arabic digits too.
    s = (text or "").strip()
    mapping = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    s = s.translate(mapping)
    digits = "".join(ch for ch in s.split()[0] if ch.isdigit()) if s.split() else ""
    return int(digits) if digits.isdigit() else None


def _resolve_target_id(update: Update, text: str) -> int | None:
    """Target = replied-to user, else a numeric ID in the text, else the sender."""
    message = update.effective_message
    if message.reply_to_message and message.reply_to_message.from_user is not None:
        return message.reply_to_message.from_user.id
    uid = _parse_int(text)
    if uid is not None:
        return uid
    user = update.effective_user
    return user.id if user is not None else None


async def _answer(query, text: str | None = None, alert: bool = False) -> None:
    try:
        await query.answer(text, show_alert=alert)
    except (BadRequest, TelegramError):
        pass


async def _safe_edit(query, text: str, markup: InlineKeyboardMarkup | None = None, html: bool = False) -> None:
    try:
        await query.edit_message_text(
            text, reply_markup=markup, parse_mode="HTML" if html else None
        )
    except (BadRequest, TelegramError):
        pass
