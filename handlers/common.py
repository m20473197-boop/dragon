"""Handlers for /start and /help."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from config import COMMAND_EGGS, COMMAND_FISHING, COMMAND_HUNT
from handlers.tracking import track_from_update

WELCOME_TEXT = (
    "🐉 به بازی «اژدها» خوش آمدی!\n\n"
    "در گروه، تخم اژدهاها تصادفی ظاهر می‌شن؛ با دکمه «🥚 نگهداری از تخم» سریع‌تر "
    "از بقیه اون‌ها رو بردار!\n"
    "با شکار و ماهیگیری هم ممکنه تخم پیدا کنی. وقتی زمان پرورش تموم بشه، اژدها "
    "خودکار از تخم بیرون میاد. 🐲\n\n"
    "📜 دستورهای بازی (بدون اسلش /):\n"
    f"🏹 {COMMAND_HUNT} — شکار حیوانات و گرفتن گوشت\n"
    f"🎣 {COMMAND_FISHING} — صید ماهی\n"
    f"🥚 {COMMAND_EGGS} — دیدن تخم‌ها و زمان باز شدنشون\n\n"
    "کافیه دستور رو توی گروه بفرستی!"
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_from_update(update, context)
    await update.effective_message.reply_text(WELCOME_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    track_from_update(update, context)
    await update.effective_message.reply_text(WELCOME_TEXT)
