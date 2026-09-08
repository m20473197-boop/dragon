"""In-memory pending-action state for multi-step admin flows.

Like the dragon-naming prompt this is transient UI state (not game data), so
it lives in ``context.user_data`` and is keyed per admin. Flows:

* ``add_food`` — waiting for a food type + amount (or a multiline text command)
  and a target user (defaults to the admin; a replied-to message picks the user).
"""
from __future__ import annotations

from telegram.ext import ContextTypes

ADMIN_PENDING_KEY = "admin_pending"


def set_pending(context: ContextTypes.DEFAULT_TYPE, action: str, data: dict) -> None:
    context.user_data[ADMIN_PENDING_KEY] = {"action": action, **data}


def get_pending(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    return context.user_data.get(ADMIN_PENDING_KEY)


def clear_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(ADMIN_PENDING_KEY, None)
