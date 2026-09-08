"""The «مبارزه» command, the battle message and its two buttons.

Callback data: ``bt:<action>:<battle_id>`` where action is ``atk`` or ``flee``.
The battle id is embedded so the handler can re-verify, on every press, that

* the battle still exists and is still active, and
* the presser is the player who started it (nobody can control someone else's
  fight, and buttons on a finished battle do nothing but explain why).

All rules live in :mod:`game.combat`; this module only renders and reports.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from game.combat import Enemy
from utils.text import to_fa

logger = logging.getLogger(__name__)

# Callback namespace (must not collide with dg: / claim_egg: / admin: / mk: /
# open_chest:).
PREFIX = "bt:"
ACTION_ATTACK = "atk"
ACTION_FLEE = "flee"

BTN_ATTACK = "⚔️ حمله"
BTN_FLEE = "🏃 فرار"

MSG_NO_DRAGON = "🐉 ابتدا یک اژدها را انتخاب کنید."
MSG_ALREADY_FIGHTING = "⚔️ تو همین الان درگیر یک نبرد هستی! اول اون رو تموم کن."
MSG_TOO_WEAK = "😮‍💨 اژدهای تو خیلی ضعیفه و باید استراحت کنه. اول غذاش بده."
MSG_ERROR = "❌ خطایی پیش اومد؛ دوباره امتحان کن."
MSG_NOT_YOURS = "⛔ این نبرد مال تو نیست!"
MSG_FINISHED = "این نبرد تموم شده."
MSG_NOT_FOUND = "این نبرد پیدا نشد."


# --- keyboards --------------------------------------------------------------
def battle_keyboard(battle_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    BTN_ATTACK, callback_data=f"{PREFIX}{ACTION_ATTACK}:{battle_id}"
                ),
                InlineKeyboardButton(
                    BTN_FLEE, callback_data=f"{PREFIX}{ACTION_FLEE}:{battle_id}"
                ),
            ]
        ]
    )


# --- texts ------------------------------------------------------------------
def hp_bar(current: int, maximum: int, width: int = 10) -> str:
    """A small ▰▱ health bar (never divides by zero)."""
    maximum = max(1, int(maximum))
    current = max(0, min(int(current), maximum))
    filled = int(round(width * current / maximum))
    return "▰" * filled + "▱" * (width - filled)


def start_text(dragon_name: str, enemy: Enemy) -> str:
    return (
        "⚔️ نبرد شروع شد!\n\n"
        f"🐉 {dragon_name}\n"
        "VS\n"
        f"{enemy.emoji} {enemy.name}\n\n"
        "Enemy HP:\n"
        f"❤️ {to_fa(enemy.hp)}/{to_fa(enemy.max_hp)}\n"
        f"{hp_bar(enemy.hp, enemy.max_hp)}"
    )


def turn_text(result) -> str:
    """The «نتیجه حمله» message after one exchange."""
    dragon = result.dragon
    enemy = result.enemy
    lines = [
        "⚔️ نتیجه حمله:",
        "",
        f"🐉 {dragon.name}:",
        f"🔥 Damage: {to_fa(result.dragon_damage)}",
        "",
        f"{enemy.emoji} {enemy.name}:",
        f"❤️ HP: {to_fa(result.enemy_hp_after)}/{to_fa(enemy.max_hp)}",
        hp_bar(result.enemy_hp_after, enemy.max_hp),
    ]
    if result.enemy_damage:
        lines += [
            "",
            f"{enemy.emoji} حمله‌ی دشمن: 💥 {to_fa(result.enemy_damage)}",
            f"🐉 {dragon.name}: ❤️ {to_fa(result.dragon_hp_after)}/{to_fa(dragon.max_hp)}",
            hp_bar(result.dragon_hp_after, dragon.max_hp),
        ]
    return "\n".join(lines)


def victory_text(result) -> str:
    dragon = result.dragon
    enemy = result.enemy
    lines = [
        "🎉 پیروزی!",
        "",
        f"🐉 {dragon.name} دشمن را شکست داد.",
        f"{enemy.emoji} {enemy.name} از پا درآمد!",
        "",
        "Rewards:",
    ]
    if result.xp_gained:
        lines.append(f"⭐ {to_fa(result.xp_gained)} تجربه")
    if result.obsidian:
        lines.append(f"🪨 {to_fa(result.obsidian)} ابسیدین")
    if result.aether:
        lines.append(f"✨ {to_fa(result.aether)} اتر")
    for event in result.level_ups:
        lines.append(
            f"\n🎊 لِوِل آپ! سطح {to_fa(event.new_level)} "
            f"(+{to_fa(event.max_hp_gained)} سلامت، +{to_fa(event.power_gained)} قدرت)"
        )
    lines.append(
        f"\n🐉 {dragon.name}: ❤️ {to_fa(dragon.hp)}/{to_fa(dragon.max_hp)}"
    )
    return "\n".join(lines)


def defeat_text(result) -> str:
    dragon = result.dragon
    enemy = result.enemy
    return (
        "💀 شکست خوردی!\n\n"
        f"🐉 {dragon.name} needs rest.\n"
        f"{enemy.emoji} {enemy.name} این بار قوی‌تر بود.\n\n"
        f"❤️ {to_fa(dragon.hp)}/{to_fa(dragon.max_hp)}\n"
        "اژدهات از بین نرفته، فقط ضعیف شده. غذاش بده تا دوباره قوی بشه."
    )


def flee_text(dragon_name: str, enemy: Enemy | None) -> str:
    enemy_label = f"{enemy.emoji} {enemy.name}" if enemy is not None else "دشمن"
    return (
        "🏃 فرار کردی!\n\n"
        f"🐉 {dragon_name} از {enemy_label} فرار کرد.\n"
        "هیچ جایزه‌ای نگرفتی."
    )


# --- helpers ----------------------------------------------------------------
async def _safe_answer(query, text: str | None = None, alert: bool = False) -> None:
    try:
        await query.answer(text, show_alert=alert)
    except (BadRequest, TelegramError):
        pass


async def _safe_edit(query, text: str, reply_markup=None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as exc:
        # "message is not modified" is harmless.
        if "not modified" not in str(exc).lower():
            logger.warning("Could not edit battle message: %s", exc)
    except TelegramError:
        logger.warning("Could not edit battle message", exc_info=True)


# --- command ----------------------------------------------------------------
async def battle_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """«مبارزه» — start a random PvE battle with the active dragon."""
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or user.is_bot:
        return

    combat = context.bot_data.get("combat_service")
    if combat is None:  # pragma: no cover - defensive
        logger.error("combat_service missing from bot_data")
        await message.reply_text(MSG_ERROR)
        return

    chat_id = update.effective_chat.id if update.effective_chat else None
    result = combat.start_battle(user.id, chat_id=chat_id)

    if not result.success:
        if result.reason == "no_dragon":
            await message.reply_text(MSG_NO_DRAGON)
        elif result.reason == "already_fighting":
            await message.reply_text(MSG_ALREADY_FIGHTING)
        elif result.reason == "too_weak":
            await message.reply_text(MSG_TOO_WEAK)
        else:
            await message.reply_text(MSG_ERROR)
        return

    sent = None
    try:
        sent = await message.reply_text(
            start_text(result.dragon.name, result.enemy),
            reply_markup=battle_keyboard(result.battle.battle_id),
        )
    except (BadRequest, TelegramError):
        logger.warning(
            "Could not send battle message for user %s", user.id, exc_info=True
        )
        # Do not leave the player locked into a battle they cannot see.
        combat.flee(result.battle.battle_id, user.id)
        return

    if sent is not None:
        try:
            combat.battles.set_message_id(result.battle.battle_id, sent.message_id)
        except Exception:
            logger.exception("Could not store battle message id")


# --- callback ---------------------------------------------------------------
async def battle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle «⚔️ حمله» and «🏃 فرار»."""
    query = update.callback_query
    if query is None or query.from_user is None or query.from_user.is_bot:
        return

    combat = context.bot_data.get("combat_service")
    if combat is None:  # pragma: no cover - defensive
        await _safe_answer(query, MSG_ERROR, alert=True)
        return

    data = query.data or ""
    parts = data[len(PREFIX):].split(":") if data.startswith(PREFIX) else []
    if len(parts) != 2:
        await _safe_answer(query)
        return
    action, raw_id = parts
    try:
        battle_id = int(raw_id)
    except ValueError:
        await _safe_answer(query)
        return

    user = query.from_user

    try:
        if action == ACTION_FLEE:
            await _handle_flee(query, combat, battle_id, user.id)
        elif action == ACTION_ATTACK:
            await _handle_attack(query, combat, battle_id, user.id)
        else:
            await _safe_answer(query)
    except Exception:
        logger.exception(
            "battle_callback failed (action=%s battle=%s user=%s)",
            action, battle_id, user.id,
        )
        await _safe_answer(query, MSG_ERROR, alert=True)


async def _reject(query, reason: str) -> None:
    """Explain why a press did nothing, and clear a dead battle's buttons."""
    if reason == "not_owner":
        await _safe_answer(query, MSG_NOT_YOURS, alert=True)
        return
    if reason == "finished":
        await _safe_answer(query, MSG_FINISHED, alert=True)
    elif reason == "not_found":
        await _safe_answer(query, MSG_NOT_FOUND, alert=True)
    else:
        await _safe_answer(query, MSG_ERROR, alert=True)
    # A battle that can no longer be played must not keep clickable buttons.
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except (BadRequest, TelegramError):
        pass


async def _handle_attack(query, combat, battle_id: int, user_id: int) -> None:
    result = combat.attack(battle_id, user_id)
    if not result.success:
        await _reject(query, result.reason)
        return

    await _safe_answer(query)

    if result.won:
        await _safe_edit(query, victory_text(result), reply_markup=None)
    elif result.lost:
        await _safe_edit(query, defeat_text(result), reply_markup=None)
    else:
        await _safe_edit(
            query, turn_text(result), reply_markup=battle_keyboard(battle_id)
        )


async def _handle_flee(query, combat, battle_id: int, user_id: int) -> None:
    result = combat.flee(battle_id, user_id)
    if not result.success:
        await _reject(query, result.reason)
        return

    await _safe_answer(query, "🏃 فرار کردی!")
    dragon_name = result.dragon.name if result.dragon else "اژدها"
    await _safe_edit(query, flee_text(dragon_name, result.enemy), reply_markup=None)
