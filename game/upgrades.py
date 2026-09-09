"""Dragon upgrades (no Telegram code here).

An upgrade permanently improves ONE dragon — currently ❤️ max HP, 🔥 power or
⭐ level — and is paid for with 🪨 obsidian. Food is never spent on upgrades.

The ⭐ level upgrade is priced **progressively**: the cost depends on the
dragon's CURRENT level (see :func:`level_upgrade_cost`), so levelling from 9 to
10 costs far more than 1 to 2. The flat ❤️ HP and ⚔️ power upgrades keep their
fixed ``cost_obsidian`` price from ``config.UPGRADES``.

Everything runs in a single transaction with a guarded spend, so a balance can
never go negative and a double tap can never apply an upgrade twice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from config import (
    LEVEL_UP_MAX_HP_BONUS,
    LEVEL_UP_POWER_BONUS,
    UPGRADE_COST_BASE,
    UPGRADE_COST_DIVISOR,
    UPGRADE_COST_EXPONENT,
    UPGRADE_COST_FORMULA_FROM,
    UPGRADE_COST_TABLE,
    UPGRADES,
)
from database.connection import get_db
from models.dragon import Dragon, DragonRepository
from models.player import PlayerRepository

# Upgrades are always paid in obsidian.
CURRENCY_COLUMN = "obsidian"

# The upgrade whose price scales with the dragon's level.
LEVEL_UPGRADE_KEY = "level"


def level_upgrade_cost(current_level: int) -> int:
    """Obsidian needed to take a dragon from ``current_level`` to the next one.

    Levels 1..9 come from the hand-tuned ``UPGRADE_COST_TABLE``; from level 10
    up the cost is extrapolated::

        cost = round(40000 * (level / 10) ** 1.8)

    Both branches give 40000 at level 10, so the curve is continuous. Levels
    below 1 (corrupt data) are clamped to the level-1 price rather than
    returning something free.
    """
    level = int(current_level)
    if level < 1:
        level = 1
    if level in UPGRADE_COST_TABLE:
        return UPGRADE_COST_TABLE[level]
    if level < UPGRADE_COST_FORMULA_FROM:
        # Defensive: a gap in the table falls back to the formula rather than
        # charging nothing.
        return round(UPGRADE_COST_BASE * (level / UPGRADE_COST_DIVISOR) ** UPGRADE_COST_EXPONENT)
    return round(UPGRADE_COST_BASE * (level / UPGRADE_COST_DIVISOR) ** UPGRADE_COST_EXPONENT)


@dataclass
class UpgradeResult:
    """Outcome of applying one upgrade to one dragon."""

    success: bool
    reason: str = ""                    # "no_dragon" | "unknown" | "not_enough"
    upgrade_key: Optional[str] = None
    dragon: Optional[Dragon] = None     # state after the upgrade
    spent: int = 0                      # obsidian paid
    missing: int = 0                    # obsidian still needed, if rejected
    balance: int = 0                    # obsidian left afterwards
    gains: dict = field(default_factory=dict)    # {"max_hp": 20, ...}
    previous_level: int = 0             # dragon level before the upgrade
    next_cost: int = 0                  # obsidian the NEXT level will cost


class UpgradeService:
    def __init__(
        self,
        dragons: Optional[DragonRepository] = None,
        players: Optional[PlayerRepository] = None,
    ) -> None:
        self.dragons = dragons or DragonRepository()
        self.players = players or PlayerRepository()

    # --- reading -----------------------------------------------------------
    def available(self) -> dict[str, dict]:
        """All configured upgrades (key -> definition)."""
        return UPGRADES

    def price(self, upgrade_key: str, dragon_level: Optional[int] = None) -> int:
        """Obsidian price of an upgrade (0 for an unknown key).

        The ⭐ level upgrade scales with ``dragon_level`` (the dragon's current
        level). Omitting it falls back to the flat configured price, which is
        only meaningful for the non-level upgrades.
        """
        spec = UPGRADES.get(upgrade_key)
        if spec is None:
            return 0
        if upgrade_key == LEVEL_UPGRADE_KEY and dragon_level is not None:
            return level_upgrade_cost(dragon_level)
        return int(spec["cost_obsidian"])

    def price_for_dragon(self, upgrade_key: str, dragon) -> int:
        """Price of an upgrade for a specific dragon."""
        level = getattr(dragon, "level", None)
        return self.price(upgrade_key, dragon_level=level)

    def balance(self, owner_id: int) -> int:
        """The owner's obsidian balance (0 for an unknown player)."""
        player = self.players.get(owner_id)
        return player.obsidian if player else 0

    def affordable(self, owner_id: int, upgrade_key: str,
                   dragon_level: Optional[int] = None) -> bool:
        """Whether the owner currently has enough obsidian for this upgrade."""
        if upgrade_key not in UPGRADES:
            return False
        return self.balance(owner_id) >= self.price(upgrade_key, dragon_level)

    def missing_for(self, owner_id: int, upgrade_key: str,
                    dragon_level: Optional[int] = None) -> int:
        """How much obsidian is still needed (0 when affordable)."""
        if upgrade_key not in UPGRADES:
            return 0
        return max(0, self.price(upgrade_key, dragon_level) - self.balance(owner_id))

    # --- applying ----------------------------------------------------------
    def apply(self, owner_id: int, dragon_id: int, upgrade_key: str) -> UpgradeResult:
        """Upgrade one dragon owned by ``owner_id``, paying in obsidian.

        Ownership is enforced, so an upgrade can never touch another dragon or
        another player's dragon.
        """
        spec = UPGRADES.get(upgrade_key)
        if spec is None or spec["stat"] not in ("max_hp", "power", "level"):
            # Validated before any payment so a misconfigured upgrade can
            # never charge the player.
            return UpgradeResult(success=False, reason="unknown")

        with get_db() as conn:
            dragon = self.dragons.get_owned(dragon_id, owner_id, conn=conn)
            if dragon is None:
                return UpgradeResult(success=False, reason="no_dragon")

            # Price is resolved from the dragon's CURRENT level, read inside
            # the same transaction as the spend, so a concurrent upgrade can
            # never be charged at a stale (cheaper) level.
            price = self.price(upgrade_key, dragon_level=dragon.level)
            # Guarded spend: fails (changing nothing) when the balance is short,
            # so obsidian can never go negative even on a double tap.
            if price > 0 and not self.players.spend_currency(
                owner_id, CURRENCY_COLUMN, price, conn=conn
            ):
                player = self.players.get(owner_id, conn=conn)
                balance = player.obsidian if player else 0
                return UpgradeResult(
                    success=False, reason="not_enough",
                    upgrade_key=upgrade_key, dragon=dragon,
                    missing=max(0, price - balance), balance=balance,
                )

            previous_level = dragon.level
            level, xp = dragon.level, dragon.xp
            max_hp, power, hp = dragon.max_hp, dragon.power, dragon.hp
            gains: dict[str, int] = {}
            stat, amount = spec["stat"], spec["amount"]

            if stat == "max_hp":
                max_hp += amount
                hp = max_hp                     # a bigger heart heals it fully
                gains["max_hp"] = amount
            elif stat == "power":
                power += amount
                gains["power"] = amount
            elif stat == "level":
                level += amount
                # A level gained this way grants the usual per-level bonuses.
                max_hp += LEVEL_UP_MAX_HP_BONUS * amount
                power += LEVEL_UP_POWER_BONUS * amount
                hp = max_hp
                gains.update(
                    level=amount,
                    max_hp=LEVEL_UP_MAX_HP_BONUS * amount,
                    power=LEVEL_UP_POWER_BONUS * amount,
                )

            self.dragons.update_growth(
                dragon.id, level=level, xp=xp, hp=hp, max_hp=max_hp,
                power=power, conn=conn,
            )
            updated = self.dragons.get(dragon.id, conn=conn)
            player = self.players.get(owner_id, conn=conn)

        return UpgradeResult(
            success=True, upgrade_key=upgrade_key, dragon=updated,
            spent=price, balance=player.obsidian if player else 0, gains=gains,
            previous_level=previous_level,
            next_cost=level_upgrade_cost(updated.level) if updated else 0,
        )


def upgrade_display(upgrade_key: str) -> tuple[str, str]:
    """Return (emoji, persian_name) for an upgrade."""
    spec = UPGRADES[upgrade_key]
    return spec["emoji"], spec["name"]
