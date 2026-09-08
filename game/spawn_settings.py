"""Egg-spawn interval setting (single source of truth).

The interval between two eggs in the same group comes from
``config.EGG_SPAWN_INTERVAL`` (env ``DRAGON_EGG_SPAWN_INTERVAL``; production
7200 = 2 hours, testing e.g. 60). Admins can change it at runtime through the
panel without touching the rest of the system — the override is kept here so
every caller reads one value and it can be reset back to the configured one.

Only the *frequency* lives here; collecting, storing and hatching eggs are
untouched.
"""
from __future__ import annotations

from typing import Optional

import config

# None -> use the configured value; int -> runtime override (admin panel).
_override_seconds: Optional[int] = None

# Choices offered by the admin panel (seconds, label).
INTERVAL_CHOICES: list[tuple[int, str]] = [
    (60, "۱ دقیقه (تست)"),
    (90 * 60, "۹۰ دقیقه"),
    (2 * 60 * 60, "۲ ساعت"),
    (0, "بازنشانی"),
]


def get_interval() -> int:
    """The effective number of seconds between eggs in one group."""
    if _override_seconds is not None:
        return _override_seconds
    return int(config.EGG_SPAWN_INTERVAL)


def set_interval(seconds: Optional[int]) -> None:
    """Set (or clear with ``None``) the runtime interval override."""
    global _override_seconds
    if seconds is None:
        _override_seconds = None
        return
    seconds = int(seconds)
    if seconds < 0:
        raise ValueError("interval must be non-negative")
    _override_seconds = seconds


def active() -> bool:
    """Whether a runtime override is currently in effect."""
    return _override_seconds is not None


def current() -> Optional[int]:
    return _override_seconds
