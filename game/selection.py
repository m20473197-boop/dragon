"""Selected dragon vs. active dragon — the two are deliberately different.

* **Selected dragon** (``selected_dragon_id``) is *temporary*. It only means
  "the dragon whose page the user is looking at right now" and drives viewing,
  feeding, upgrading and renaming. It lives for the duration of the
  interaction/session and is never written to the players table.
* **Active dragon** (``active_dragon_id``) is *permanent*. It is stored on the
  players row and is the dragon that represents the player elsewhere in the
  game — combat reads this and nothing else. It changes **only** when the user
  presses «⭐ انتخاب به عنوان اژدهای فعال».

Opening a dragon's profile therefore must never touch the active dragon.

This module keeps the session state as plain helper functions over a dict, so
the rules stay testable without importing python-telegram-bot (the handler
passes ``context.user_data``).
"""
from __future__ import annotations

from typing import Any, MutableMapping, Optional

# Key used inside ``context.user_data``.
SELECTED_DRAGON_KEY = "selected_dragon_id"


def set_selected_dragon(
    session: Optional[MutableMapping[str, Any]], dragon_id: Optional[int]
) -> None:
    """Remember which dragon the user is currently looking at.

    This is session-only state: it is never persisted and never affects
    ``active_dragon_id``.
    """
    if session is None:
        return
    if dragon_id is None:
        session.pop(SELECTED_DRAGON_KEY, None)
    else:
        session[SELECTED_DRAGON_KEY] = int(dragon_id)


def get_selected_dragon(
    session: Optional[MutableMapping[str, Any]]
) -> Optional[int]:
    """The dragon currently being viewed, or ``None``."""
    if session is None:
        return None
    value = session.get(SELECTED_DRAGON_KEY)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def clear_selected_dragon(session: Optional[MutableMapping[str, Any]]) -> None:
    """Forget the current selection (e.g. back to the list)."""
    set_selected_dragon(session, None)
