"""Dragon upgrades (no Telegram code here).

An upgrade permanently improves ONE dragon — currently ❤️ max HP, 🔥 power or
⭐ level — and is paid for with 🪨 obsidian. Food is never spent on upgrades.
Prices are declared in ``config.UPGRADES`` as ``cost_obsidian``, so new
upgrades (or new prices) are a configuration change alone.

Everything runs in a single transaction with a guarded spend, so a balance can
never go negative and a double tap can never apply an upgrade twice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from config import (
    LEVEL_UP_MAX_HP_BONUS,
    LEVEL_UP_POWER_BONUS,
    UPGRADES,
)
from database.connection import get_db
from models.dragon import Dragon, DragonRepository
from models.player import PlayerRepository

# Upgrades are always paid in obsidian.
CURRENCY_COLUMN = "obsidian"


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

    def price(self, upgrade_key: str) -> int:
        """Obsidian price of an upgrade (0 for an unknown key)."""
        spec = UPGRADES.get(upgrade_key)
        return int(spec["cost_obsidian"]) if spec else 0

    def balance(self, owner_id: int) -> int:
        """The owner's obsidian balance (0 for an unknown player)."""
        player = self.players.get(owner_id)
        return player.obsidian if player else 0

    def affordable(self, owner_id: int, upgrade_key: str) -> bool:
        """Whether the owner currently has enough obsidian for this upgrade."""
        if upgrade_key not in UPGRADES:
            return False
        return self.balance(owner_id) >= self.price(upgrade_key)

    def missing_for(self, owner_id: int, upgrade_key: str) -> int:
        """How much obsidian is still needed (0 when affordable)."""
        if upgrade_key not in UPGRADES:
            return 0
        return max(0, self.price(upgrade_key) - self.balance(owner_id))

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

            price = int(spec["cost_obsidian"])
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
        )


def upgrade_display(upgrade_key: str) -> tuple[str, str]:
    """Return (emoji, persian_name) for an upgrade."""
    spec = UPGRADES[upgrade_key]
    return spec["emoji"], spec["name"]
