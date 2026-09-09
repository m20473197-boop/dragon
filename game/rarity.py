"""Dragon rarity and egg origin rules (Version 8) — no Telegram code here.

An egg no longer produces identical dragons. When it hatches, two things are
rolled:

* the **element** (which ``DRAGON_TYPES`` key the dragon is) — either fixed by
  the egg type (a 🔥 flame egg always yields a fire dragon) or drawn from the
  egg's weighted pool;
* the **rarity** — drawn from the egg's own rarity table.

Rarity then scales the newborn's starting HP and power. It is stored once on
the dragon row and never changes: levelling, feeding and upgrades all keep
working on the resulting numbers exactly as before.
"""
from __future__ import annotations

from typing import Optional

from config import (
    DEFAULT_RARITY,
    DRAGON_DEFAULT_MAX_HP,
    DRAGON_DEFAULT_POWER,
    DRAGON_TYPES,
    EGG_TYPES,
    RARITIES,
)
from utils.rng import weighted_choice


# --- rarity helpers ---------------------------------------------------------
def normalise_rarity(rarity: Optional[str]) -> str:
    """Coerce anything unknown/missing to the default ⚪ معمولی.

    Old dragons, hand-edited rows and future keys that were removed from the
    config all degrade gracefully instead of crashing a screen.
    """
    if rarity and rarity in RARITIES:
        return rarity
    return DEFAULT_RARITY


def rarity_display(rarity: str) -> tuple[str, str]:
    """Return ``(emoji, persian_name)`` for a rarity."""
    info = RARITIES[normalise_rarity(rarity)]
    return info["emoji"], info["name"]


def rarity_label(rarity: str) -> str:
    """Compact «🔵 حماسی» label used across the UI."""
    emoji, name = rarity_display(rarity)
    return f"{emoji} {name}"


def rarity_multiplier(rarity: str) -> float:
    """Stat multiplier for a rarity (1.0 for ⚪ معمولی)."""
    return RARITIES[normalise_rarity(rarity)]["multiplier"]


def rarity_order(rarity: str) -> int:
    """Sort key: higher means rarer."""
    return RARITIES[normalise_rarity(rarity)]["order"]


def element_display(dragon_type: str) -> tuple[str, str]:
    """Return ``(emoji, element_name)`` for a dragon type, e.g. ``("🔥", "آتش")``."""
    info = DRAGON_TYPES.get(dragon_type)
    if info is None:
        return "🐉", dragon_type
    return info["emoji"], info.get("element", info["name"])


def element_label(dragon_type: str) -> str:
    """Compact «🔥 آتش» label."""
    emoji, name = element_display(dragon_type)
    return f"{emoji} {name}"


# --- stat generation --------------------------------------------------------
def scaled_stats(
    rarity: str,
    base_max_hp: int = DRAGON_DEFAULT_MAX_HP,
    base_power: int = DRAGON_DEFAULT_POWER,
) -> tuple[int, int]:
    """Starting ``(max_hp, power)`` for a newborn of the given rarity.

    ⚪ معمولی returns the base stats unchanged, so a normal dragon born after
    this change is identical to one born before it.
    """
    multiplier = rarity_multiplier(rarity)
    return (
        max(1, int(round(base_max_hp * multiplier))),
        max(1, int(round(base_power * multiplier))),
    )


# --- rolling ----------------------------------------------------------------
def rarity_table(egg_type: str) -> dict[str, int]:
    """The rarity chances of an egg type (falls back to always-normal)."""
    spec = EGG_TYPES.get(egg_type) or {}
    table = spec.get("rarity")
    if not table:
        return {DEFAULT_RARITY: 100}
    # Drop any rarity key that is not configured, so a typo cannot crash a hatch.
    cleaned = {k: v for k, v in table.items() if k in RARITIES and v > 0}
    return cleaned or {DEFAULT_RARITY: 100}


def roll_rarity(egg_type: str) -> str:
    """Pick a rarity for a dragon hatching from ``egg_type``."""
    return weighted_choice(rarity_table(egg_type))


def roll_element(egg_type: str) -> str:
    """Pick the element for a dragon hatching from ``egg_type``.

    Eggs with a fixed ``element`` always produce that element; the others roll
    from their weighted ``dragons`` pool (the pre-V8 behaviour).
    """
    spec = EGG_TYPES.get(egg_type) or {}
    element = spec.get("element")
    if element and element in DRAGON_TYPES:
        return element
    pool = {k: v for k, v in (spec.get("dragons") or {}).items() if k in DRAGON_TYPES}
    if not pool:
        # Unknown/legacy egg: fall back to the common egg's pool so a hatch can
        # never fail because of configuration drift.
        pool = EGG_TYPES["common"]["dragons"]
    return weighted_choice(pool)


def egg_is_special(egg_type: str) -> bool:
    """True when an egg can only come from rewards/events (never spawns wild)."""
    return (EGG_TYPES.get(egg_type) or {}).get("weight", 0) <= 0
