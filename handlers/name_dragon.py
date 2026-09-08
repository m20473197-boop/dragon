"""Handler for the نام اژدها (name your dragon) command and the name capture.

Flow:
1. User sends «نام اژدها». The bot names their most recent dragon and asks for
   a name, storing a short-lived pending state in ``context.user_data``.
2. The user's next non-command text message is treated as the name. Sending any
   game command cancels the prompt and runs that command as usual.

The naming state is per-user and in-memory (it is a temporary prompt, not
game data — the saved name lives in the database).
"""
from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from config import (
    DRAGON_NAME_MAX_LENGTH,
    NAME_PROMPT_TIMEOUT_SECONDS,
)
from utils.text import to_fa

logger = logging.getLogger(__name__)

# user_data keys for the naming prompt.
NAME_STATE_KEY = "naming_dragon"        # holds {"dragon_id": int, "chat_id": int, "at": float}
NAME_TIMER_KEY = "naming_dragon_timer"  # Job name for the timeout
NAME_PROMPT_TASK = "dragon_name_prompt"


async def name_dragon_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the naming flow: pick the newest dragon and ask for a name."""
    user = update.effective_user
    message = update.effective_message
    player_repo = context.bot_data["player_repo"]
    dragon_service = context.bot_data["dragon_service"]

    player_repo.get_or_create(user.id, user.username)
    dragon = dragon_service.newest_for_owner(user.id)

    if dragon is None:
        await message.reply_text(
            "🐉 هنوز اژدهایی نداری که نامش رو تعیین کنی!\n"
            "اول یک تخم اژدها بگیر و صبر کن تا اژدها ازش بیرون بیاد. 🥚"
        )
        return

    _begin_prompt(context, user_id=user.id, dragon_id=dragon.id, chat_id=update.effective_chat.id)

    await message.reply_text(
        f"📛 برای اژدهات یک نام بفرست.\n\n"
        f"نام باید بین ۱ تا {to_fa(DRAGON_NAME_MAX_LENGTH)} حرف باشه. "
        f"اگه نمی‌خوای نام‌گذاری کنی، یک دستور بازی (مثل «شکار») بفرست تا لغو بشه."
    )


async def capture_dragon_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle a pending naming prompt, if one exists for this user.

    Returns ``True`` if the message was consumed by the naming flow (so the
    router should stop), ``False`` if there is no active prompt (normal
    command routing continues).
    """
    user = update.effective_user
    message = update.effective_message
    state: Optional[dict] = context.user_data.get(NAME_STATE_KEY)
    if state is None:
        return False

    # Only the message in the chat where the prompt started is captured, and
    # the incoming text must be the answer (router already excluded commands).
    if update.effective_chat is None or state.get("chat_id") != update.effective_chat.id:
        return False

    raw_name = (message.text or "").strip()
    # Command-like input cancels the prompt (router handles it as a command).
    if raw_name.startswith("/") or not raw_name:
        _cancel_prompt(context)
        return False

    dragon_service = context.bot_data["dragon_service"]
    dragon_id = state["dragon_id"]

    # Validate length.
    if len(raw_name) > DRAGON_NAME_MAX_LENGTH:
        await message.reply_text(
            f"⚠️ نام خیلی بلنده! حداکثر {to_fa(DRAGON_NAME_MAX_LENGTH)} حرف بفرست."
        )
        return True  # consume the message; the prompt stays open

    renamed = dragon_service.rename(user.id, dragon_id, raw_name)
    _cancel_prompt(context)

    if renamed is None:
        await message.reply_text(
            "نشد نام اژدها رو ذخیره کنم؛ لطفاً دوباره «نام اژدها» رو بفرست."
        )
        return True

    await message.reply_text(
        f"✅ تمام شد! از این به بعد اژدهات «{renamed.name}» صدا زده می‌شه. 🐉"
    )
    return True


# --- small state helpers ----------------------------------------------------
def start_naming_for_dragon(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, dragon_id: int, chat_id: int
) -> None:
    """Public hook: open a naming prompt for one specific dragon.

    Used by the dragon management panel («✏️ تغییر نام») so the captured name
    is applied to the dragon the user selected, instead of the newest one.
    """
    _begin_prompt(context, user_id=user_id, dragon_id=dragon_id, chat_id=chat_id)


def cancel_naming_prompt(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Public hook: discard any open naming prompt for this user.

    Called when the user sends a real game command so the command's reply is
    not later mistaken for a dragon name.
    """
    _cancel_prompt(context)


def _begin_prompt(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, dragon_id: int, chat_id: int
) -> None:
    """Start a naming prompt for the current user, replacing any prior one."""
    _cancel_prompt(context)
    import time

    context.user_data[NAME_STATE_KEY] = {
        "dragon_id": dragon_id,
        "chat_id": chat_id,
        "at": time.time(),
    }
    _schedule_timeout(context, user_id=user_id, chat_id=chat_id)


def _cancel_prompt(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear the naming prompt state and any pending timeout job."""
    context.user_data.pop(NAME_STATE_KEY, None)
    if context.job_queue is None:
        return
    for job in list(context.job_queue.get_jobs_by_name(NAME_PROMPT_TASK)):
        job.schedule_removal()


def _schedule_timeout(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int
) -> None:
    """If the user never replies, drop the prompt after a while."""
    if context.job_queue is None:
        return
    context.job_queue.run_once(
        _prompt_timeout,
        when=NAME_PROMPT_TIMEOUT_SECONDS,
        name=NAME_PROMPT_TASK,
        data={"chat_id": chat_id},
        user_id=user_id,
        chat_id=chat_id,
    )


async def _prompt_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: silently clear an abandoned prompt."""
    context.user_data.pop(NAME_STATE_KEY, None)
