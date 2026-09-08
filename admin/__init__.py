"""Admin panel package (development / testing / monitoring).

Organised into focused modules:

* ``permissions``  — admin allow-list and DEBUG_MODE gating.
* ``service``      — admin-only database operations (no Telegram code).
* ``keyboards``    — inline keyboards for the panel.
* ``handlers``     — Telegram command/callback handlers.
"""
from __future__ import annotations

from admin.handlers import admin_capture
from admin.permissions import is_admin

__all__ = ["admin_capture", "is_admin"]
