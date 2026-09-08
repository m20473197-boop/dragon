"""Testing-only hatch-time override.

Used by the admin panel to make test eggs hatch quickly (10s / 1min / 5min).
It is deliberately a separate, debug-only value — production hatch times in
``config.EGG_TYPES`` are never modified. All access goes through here so the
feature is easy to switch off and to reset back to production.
"""
from __future__ import annotations

from typing import Optional

# None  -> use production config times
# int   -> every egg hatches after this many seconds (testing override)
_override_seconds: Optional[int] = None


def get_hatch_seconds(default_seconds: int) -> int:
    """Return the effective hatch time for an egg.

    Uses the debug override if set, otherwise the production value.
    """
    return _override_seconds if _override_seconds is not None else default_seconds


def set_hatch_seconds(seconds: Optional[int]) -> None:
    """Set/clear the testing override (None resets to production)."""
    global _override_seconds
    _override_seconds = int(seconds) if seconds is not None else None


def active() -> bool:
    """Whether a testing override is currently active."""
    return _override_seconds is not None


def current() -> Optional[int]:
    return _override_seconds
