"""Tool progression: 🎣 fishing rods and 🏹 hunting weapons (no Telegram code).

Every player owns both tools, starting at level 1. A tool's level decides the
reward range of its gathering action, and hunting weapons additionally decide
which prey can be caught. Upgrades are paid in 🪨 obsidian, one level at a
time, up to ``config.TOOL_MAX_LEVEL``.

The payment and the level increment happen in ONE guarded UPDATE
(``PlayerRepository.upgrade_tool``), so a double tap can never skip a level,
overspend, or push a tool past the cap.

No durability, crafting or trading — only levels.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config import (
    FISHING_RODS,
    HUNTING_WEAPONS,
    HUNT_PREY,
    TOOL_MAX_LEVEL,
    TOOL_MIN_LEVEL,
)
from models.player import PlayerRepository

# Tool kinds, and how each maps onto its config table and player column.
ROD = "rod"
WEAPON = "weapon"

TOOLS: dict[str, dict] = {
    ROD: {
        "column": "rod_level",
        "levels": FISHING_RODS,
        "emoji": "🎣",
        "title": "قلاب",          # «🎣 قلاب: Lv.3»
        "resource": "fish",
    },
    WEAPON: {
        "column": "weapon_level",
        "levels": HUNTING_WEAPONS,
        "emoji": "🏹",
        "title": "ابزار شکار",
        "resource": "meat",
    },
}


def _spec(kind: str) -> dict:
    if kind not in TOOLS:
        raise ValueError(f"Unknown tool kind: {kind!r}")
    return TOOLS[kind]


def clamp_level(level: int) -> int:
    """Keep a level inside [TOOL_MIN_LEVEL, TOOL_MAX_LEVEL].

    Guards the display and reward paths against corrupt or out-of-range rows,
    so a bad value can never crash gathering or hand out a huge reward.
    """
    try:
        level = int(level)
    except (TypeError, ValueError):
        return TOOL_MIN_LEVEL
    return max(TOOL_MIN_LEVEL, min(TOOL_MAX_LEVEL, level))


def tool_info(kind: str, level: int) -> dict:
    """The config entry for one tool at one level (level is clamped)."""
    return _spec(kind)["levels"][clamp_level(level)]


def tool_display(kind: str, level: int) -> tuple[str, str]:
    """``(emoji, name)`` of a tool at a level, e.g. ``("🎣", "قلاب فولادی")``."""
    info = tool_info(kind, level)
    return info["emoji"], info["name"]


def reward_range(kind: str, level: int) -> tuple[int, int]:
    """``(min, max)`` resources this tool rolls at ``level``."""
    info = tool_info(kind, level)
    return int(info["min"]), int(info["max"])


def upgrade_cost(kind: str, current_level: int) -> int:
    """Obsidian needed to go from ``current_level`` to the next one.

    Returns 0 at the cap (there is nothing to buy).
    """
    level = clamp_level(current_level)
    if level >= TOOL_MAX_LEVEL:
        return 0
    return int(_spec(kind)["levels"][level + 1]["cost"])


def is_max_level(level: int) -> bool:
    return clamp_level(level) >= TOOL_MAX_LEVEL


def allowed_prey(level: int) -> tuple[str, ...]:
    """Prey keys a hunting weapon can catch at ``level``.

    Unknown keys are filtered out, and the level-1 roster is used as a
    fallback, so a config typo can never leave hunting with nothing to catch.
    """
    keys = tuple(HUNTING_WEAPONS[clamp_level(level)].get("prey", ()))
    valid = tuple(k for k in keys if k in HUNT_PREY)
    if valid:
        return valid
    fallback = tuple(
        k for k in HUNTING_WEAPONS[TOOL_MIN_LEVEL].get("prey", ()) if k in HUNT_PREY
    )
    return fallback or tuple(HUNT_PREY)


@dataclass
class ToolUpgradeResult:
    """Outcome of one tool upgrade attempt."""

    success: bool
    reason: str = ""              # "unknown" | "max_level" | "not_enough"
    kind: str = ""
    previous_level: int = 0
    level: int = 0                # level after the upgrade
    spent: int = 0
    balance: int = 0              # obsidian left afterwards
    missing: int = 0              # obsidian still needed, when rejected
    next_cost: int = 0            # cost of the level after this one (0 at cap)


class ToolService:
    """Reads tool levels and applies paid upgrades."""

    def __init__(self, players: Optional[PlayerRepository] = None) -> None:
        self.players = players or PlayerRepository()

    # --- reading -----------------------------------------------------------
    def level(self, user_id: int, kind: str) -> int:
        """The player's current level for a tool (1 when unknown)."""
        column = _spec(kind)["column"]
        return clamp_level(self.players.get_tool_level(user_id, column))

    def levels(self, user_id: int) -> dict[str, int]:
        """Both tool levels at once, for screens that show them together."""
        player = self.players.get(user_id)
        if player is None:
            return {ROD: TOOL_MIN_LEVEL, WEAPON: TOOL_MIN_LEVEL}
        return {
            ROD: clamp_level(player.rod_level),
            WEAPON: clamp_level(player.weapon_level),
        }

    def balance(self, user_id: int) -> int:
        player = self.players.get(user_id)
        return player.obsidian if player else 0

    def cost_for(self, user_id: int, kind: str) -> int:
        """Obsidian needed for this player's next upgrade of ``kind``."""
        return upgrade_cost(kind, self.level(user_id, kind))

    # --- upgrading ---------------------------------------------------------
    def upgrade(self, user_id: int, kind: str) -> ToolUpgradeResult:
        """Raise one tool by one level, paying in obsidian."""
        if kind not in TOOLS:
            return ToolUpgradeResult(success=False, reason="unknown")

        column = _spec(kind)["column"]
        # Make sure the row exists before reading/updating it.
        self.players.get_or_create(user_id, None)

        current = clamp_level(self.players.get_tool_level(user_id, column))
        balance = self.balance(user_id)

        if current >= TOOL_MAX_LEVEL:
            return ToolUpgradeResult(
                success=False, reason="max_level", kind=kind,
                previous_level=current, level=current, balance=balance,
            )

        cost = upgrade_cost(kind, current)
        if balance < cost:
            return ToolUpgradeResult(
                success=False, reason="not_enough", kind=kind,
                previous_level=current, level=current,
                balance=balance, missing=cost - balance, next_cost=cost,
            )

        # Guarded: pays and levels up together, or does nothing at all.
        if not self.players.upgrade_tool(
            user_id, column, cost, expected_level=current,
            max_level=TOOL_MAX_LEVEL,
        ):
            # Lost a race (someone/something changed the row first). Report the
            # fresh state rather than a stale success.
            fresh = clamp_level(self.players.get_tool_level(user_id, column))
            balance = self.balance(user_id)
            if fresh >= TOOL_MAX_LEVEL:
                reason = "max_level"
            else:
                reason = "not_enough"
            return ToolUpgradeResult(
                success=False, reason=reason, kind=kind,
                previous_level=fresh, level=fresh, balance=balance,
                missing=max(0, upgrade_cost(kind, fresh) - balance),
                next_cost=upgrade_cost(kind, fresh),
            )

        new_level = current + 1
        return ToolUpgradeResult(
            success=True, kind=kind, previous_level=current, level=new_level,
            spent=cost, balance=self.balance(user_id),
            next_cost=upgrade_cost(kind, new_level),
        )
