"""Admin authorization and debug gating.

Access is based purely on the Telegram user ID allow-list in
``config.ADMIN_IDS`` (populated from the ``DRAGON_ADMIN_IDS`` environment
variable). Testing tools additionally require ``config.DEBUG_MODE``.
"""
from __future__ import annotations

from config import ADMIN_IDS, DEBUG_MODE


def is_admin(user_id: int | None) -> bool:
    """True only for IDs on the admin allow-list."""
    return user_id is not None and user_id in ADMIN_IDS


def debug_enabled() -> bool:
    """Whether testing tools are available."""
    return bool(DEBUG_MODE)


def can_use_test_tools(user_id: int | None) -> bool:
    """Admin AND debug mode required for test/dev tools."""
    return is_admin(user_id) and debug_enabled()
