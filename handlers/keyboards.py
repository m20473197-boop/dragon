"""Main reply keyboard — an accessibility layer over the Persian commands.

This module adds **no new features**. Every button simply sends the text of a
Persian command that already exists, so tapping a button is identical to the
user typing the word themselves.

The button captions carry a leading emoji (🥚 تخم‌ها) while the underlying
command word does not (تخم ها), so :data:`MENU_BUTTON_ALIASES` maps each
caption back to its command. :func:`utils.text.normalize_command` already
converts the Persian semi-space (U+200C) to a plain space, which is why
«تخم‌ها» and «تخم ها» both resolve to the same command.

Typing the bare Persian words keeps working exactly as before — the router
checks the real command table first and only then consults these aliases.
"""
from __future__ import annotations

from telegram import KeyboardButton, ReplyKeyboardMarkup

from config import (
    COMMAND_BREEDING,
    COMMAND_EGGS,
    COMMAND_MARKET,
    COMMAND_MY_DRAGONS_MENU,
    COMMAND_STORAGE,
)
from utils.text import normalize_command

# Button caption -> the existing Persian command it triggers.
# خزانه is deliberately NOT on the main menu (it stays a typed command).
MENU_BUTTONS: tuple[tuple[str, str], ...] = (
    ("🥚 تخم‌ها", COMMAND_EGGS),
    ("🐉 اژدها", COMMAND_MY_DRAGONS_MENU),
    ("❄️ سردخانه", COMMAND_STORAGE),
    ("🏪 بازار", COMMAND_MARKET),
    ("🧬 پیوند", COMMAND_BREEDING),
)

# Normalised caption -> command word, used by the router to resolve a tap.
MENU_BUTTON_ALIASES: dict[str, str] = {
    normalize_command(caption): command for caption, command in MENU_BUTTONS
}


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """The persistent main menu.

    Laid out 2 / 2 / 1 so the captions stay readable on narrow phones.
    ``is_persistent`` keeps it available instead of collapsing behind the
    keyboard icon; ``resize_keyboard`` stops it eating half the screen.
    """
    rows = [
        [KeyboardButton(MENU_BUTTONS[0][0]), KeyboardButton(MENU_BUTTONS[1][0])],
        [KeyboardButton(MENU_BUTTONS[2][0]), KeyboardButton(MENU_BUTTONS[3][0])],
        [KeyboardButton(MENU_BUTTONS[4][0])],
    ]
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="یه دکمه بزن یا دستور بنویس…",
    )


def resolve_menu_button(normalised_text: str) -> str | None:
    """Return the command word for a menu caption, or None if it is not one.

    ``normalised_text`` must already have passed through
    :func:`utils.text.normalize_command`.
    """
    return MENU_BUTTON_ALIASES.get(normalised_text)
