"""Inline keyboards for the admin panel."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from admin.permissions import debug_enabled

# Callback data prefixes/values (kept as constants to avoid typos).
PREFIX = "admin:"
CB_TEST_EGG = "test_egg"
CB_TEST_DRAGON = "test_dragon"
CB_TEST_CHEST = "test_chest"
CB_STATS = "stats"
CB_USER_INFO = "user_info"
CB_ADD_FOOD = "add_food"
CB_HATCH = "hatch"
CB_RESET = "reset"
CB_RESET_CONFIRM = "reset_confirm"
CB_BACK = "back"

HATCH_CHOICES = [(10, "۱۰ ثانیه"), (60, "۱ دقیقه"), (300, "۵ دقیقه"), (0, "بازنشانی")]
FOOD_CHOICES = ["meat", "fish"]


def panel_keyboard() -> InlineKeyboardMarkup:
    """Main admin panel. Testing buttons only appear when DEBUG_MODE is on."""
    rows: list[list[InlineKeyboardButton]] = []
    if debug_enabled():
        rows.append(
            [InlineKeyboardButton("🥚 ساخت تخم تست", callback_data=f"{PREFIX}{CB_TEST_EGG}")]
        )
        rows.append(
            [InlineKeyboardButton("🐉 ساخت اژدهای تست", callback_data=f"{PREFIX}{CB_TEST_DRAGON}")]
        )
        rows.append(
            [InlineKeyboardButton("🎁 ساخت صندوق تست", callback_data=f"{PREFIX}{CB_TEST_CHEST}")]
        )
        rows.append(
            [InlineKeyboardButton("🍖 اضافه کردن غذا", callback_data=f"{PREFIX}{CB_ADD_FOOD}")]
        )
        rows.append(
            [InlineKeyboardButton("⏩ تغییر زمان تخم", callback_data=f"{PREFIX}{CB_HATCH}")]
        )
        rows.append(
            [InlineKeyboardButton("🗑 پاک کردن اطلاعات تست", callback_data=f"{PREFIX}{CB_RESET}")]
        )
    # Monitoring tools are always available to admins.
    rows.append(
        [InlineKeyboardButton("📊 آمار بازی", callback_data=f"{PREFIX}{CB_STATS}")]
    )
    rows.append(
        [InlineKeyboardButton("👤 اطلاعات کاربر", callback_data=f"{PREFIX}{CB_USER_INFO}")]
    )
    return InlineKeyboardMarkup(rows)


def hatch_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(label, callback_data=f"{PREFIX}{CB_HATCH}:{seconds}")
            for seconds, label in HATCH_CHOICES[:2]
        ],
        [
            InlineKeyboardButton(HATCH_CHOICES[2][1], callback_data=f"{PREFIX}{CB_HATCH}:300"),
            InlineKeyboardButton(HATCH_CHOICES[3][1], callback_data=f"{PREFIX}{CB_HATCH}:0"),
        ],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"{PREFIX}{CB_BACK}")],
    ]
    return InlineKeyboardMarkup(rows)


def food_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🥩 گوشت", callback_data=f"{PREFIX}{CB_ADD_FOOD}:meat"),
                InlineKeyboardButton("🐟 ماهی", callback_data=f"{PREFIX}{CB_ADD_FOOD}:fish"),
            ],
            [InlineKeyboardButton("🔙 بازگشت", callback_data=f"{PREFIX}{CB_BACK}")],
        ]
    )


def reset_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ بله، پاک کن", callback_data=f"{PREFIX}{CB_RESET_CONFIRM}"),
                InlineKeyboardButton("❌ لغو", callback_data=f"{PREFIX}{CB_BACK}"),
            ]
        ]
    )
