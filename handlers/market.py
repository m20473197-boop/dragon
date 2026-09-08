"""Market (بازار) command, category menus and purchase buttons.

Layout:

    🏪 بازار اژدها          -> categories
      🥩 غذا                -> meat / fish, each with a [خرید] button
      🥚 تخم اژدها          -> common egg, with a [خرید] button
      ✨ آیتم‌های ویژه       -> empty, reserved for future items
      🔙 برگشت              -> back to the categories

Everything is priced in 🪨 obsidian. The service layer performs the guarded
spend, so a player can never overspend or go negative; this module only
renders the UI and reports the outcome.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from config import MARKET_CATEGORIES, MARKET_ITEMS
from game.market import list_category
from utils.text import to_fa

logger = logging.getLogger(__name__)

# Callback data: "mk:<action>[:<category>[:<item>]]".
PREFIX = "mk:"
ACTION_HOME = "home"
ACTION_CATEGORY = "cat"
ACTION_BUY = "buy"

MARKET_TITLE = "🏪 بازار اژدها"
CURRENCY = "🪨"


# --- keyboards --------------------------------------------------------------
def categories_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{spec['emoji']} {spec['name']}",
                callback_data=f"{PREFIX}{ACTION_CATEGORY}:{key}",
            )
        ]
        for key, spec in MARKET_CATEGORIES.items()
    ]
    # «🔙 برگشت» closes the market back to its main screen.
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data=f"{PREFIX}{ACTION_HOME}")])
    return InlineKeyboardMarkup(rows)


def category_keyboard(category: str) -> InlineKeyboardMarkup:
    """One «خرید» button per item, plus back to the categories."""
    rows = []
    for item_key, item in list_category(category).items():
        rows.append(
            [
                InlineKeyboardButton(
                    f"{item['emoji']} {item['name']} — {CURRENCY} {to_fa(item['price'])} | خرید",
                    callback_data=f"{PREFIX}{ACTION_BUY}:{category}:{item_key}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("🔙 برگشت", callback_data=f"{PREFIX}{ACTION_HOME}")])
    return InlineKeyboardMarkup(rows)


# --- texts ------------------------------------------------------------------
def market_text(balance: int) -> str:
    return (
        f"{MARKET_TITLE}\n\n"
        f"💰 موجودی تو: {CURRENCY} {to_fa(balance)} ابسیدین\n\n"
        "یک دسته رو انتخاب کن:"
    )


def category_text(category: str, balance: int) -> str:
    spec = MARKET_CATEGORIES[category]
    items = list_category(category)
    lines = [f"{spec['emoji']} {spec['name']}", ""]

    if not items:
        # The special category is intentionally empty for now.
        lines.append("🚧 هنوز آیتمی اینجا نیست؛ به‌زودی اضافه می‌شه!")
    else:
        for item in items.values():
            amount = item.get("amount", 1)
            unit = f" ({to_fa(amount)} عدد)" if amount > 1 else ""
            lines.append(
                f"{item['emoji']} {item['name']}{unit}\n"
                f"   قیمت: {CURRENCY} {to_fa(item['price'])} ابسیدین"
            )
        lines.append("")
        lines.append("برای خرید روی دکمه‌ی همون آیتم بزن 👇")

    lines += ["", f"💰 موجودی تو: {CURRENCY} {to_fa(balance)} ابسیدین"]
    return "\n".join(lines)


def purchase_text(result) -> str:
    """Success message for a completed purchase."""
    item = result.item
    if item["kind"] == "food":
        got = f"{item['emoji']} {to_fa(result.amount)} {item['name']} به سردخانه‌ات اضافه شد."
    else:
        got = (
            f"{item['emoji']} یک {item['name']} خریدی!\n"
            "🫧 توی «تخم ها» می‌تونی زمان باز شدنش رو ببینی."
        )
    return (
        "✅ خرید انجام شد!\n\n"
        f"{got}\n"
        f"💸 پرداختی: {CURRENCY} {to_fa(result.price)} ابسیدین\n"
        f"💰 موجودی جدید: {CURRENCY} {to_fa(result.balance)} ابسیدین"
    )


# --- command ----------------------------------------------------------------
async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«بازار» — open the market with its category buttons."""
    user = update.effective_user
    message = update.effective_message
    context.bot_data["player_repo"].get_or_create(user.id, user.username)
    balance = context.bot_data["market_service"].balance(user.id)

    await message.reply_text(market_text(balance), reply_markup=categories_keyboard())


# --- callbacks --------------------------------------------------------------
async def market_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route every «mk:» button press."""
    query = update.callback_query
    if query is None or query.from_user is None or query.from_user.is_bot:
        return

    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    user = query.from_user
    market = context.bot_data["market_service"]

    try:
        context.bot_data["player_repo"].get_or_create(user.id, user.username)

        if action == ACTION_HOME:
            await _answer(query)
            await _edit(query, market_text(market.balance(user.id)), categories_keyboard())
            return

        category = parts[2] if len(parts) > 2 else ""
        if category not in MARKET_ITEMS:
            await _answer(query)
            return

        if action == ACTION_CATEGORY:
            await _answer(query)
            await _edit(
                query,
                category_text(category, market.balance(user.id)),
                category_keyboard(category),
            )
            return

        if action == ACTION_BUY:
            item_key = parts[3] if len(parts) > 3 else ""
            chat_id = query.message.chat_id if query.message is not None else None
            result = market.buy(user.id, category, item_key, chat_id=chat_id)

            if not result.success:
                if result.reason == "not_enough":
                    await _answer(
                        query,
                        f"{CURRENCY} ابسیدین کافی نداری! "
                        f"{to_fa(result.missing)} تای دیگه لازمه.",
                        alert=True,
                    )
                elif result.reason == "failed":
                    await _answer(query, "خرید انجام نشد؛ دوباره امتحان کن.", alert=True)
                else:
                    await _answer(query, "این آیتم پیدا نشد.", alert=True)
                return

            await _answer(query, "✅ خرید انجام شد!")
            await _edit(query, purchase_text(result), category_keyboard(category))
            return

        await _answer(query)
    except Exception:
        logger.exception("Market callback failed for %s", query.data)
        await _answer(query, "خطایی پیش اومد؛ دوباره امتحان کن.", alert=True)


# --- helpers ----------------------------------------------------------------
async def _edit(query, text: str, markup: InlineKeyboardMarkup | None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except (BadRequest, TelegramError):
        logger.debug("Could not edit market message", exc_info=True)


async def _answer(query, text: str | None = None, alert: bool = False) -> None:
    try:
        await query.answer(text, show_alert=alert)
    except (BadRequest, TelegramError):
        pass
