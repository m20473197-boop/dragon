"""Dragon upgrades (no Telegram code here).

An upgrade permanently improves ONE dragon — currently ❤️ max HP, 🔥 power or
⭐ level — and is paid for with food from the owner's cold storage. There is no
coin/shop/currency system: costs are plain meat/fish amounts declared in
``config.UPGRADES``, so new upgrades can be added by editing that dict alone.

Everything runs in a single transaction with guarded spends, so a double tap
can never apply an upgrade the player cannot afford.
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
from game.storage import ColdStorageService
from models.dragon import Dragon, DragonRepository
from models.player import PlayerRepository


@dataclass
class UpgradeResult:
    """Outcome of applying one upgrade to one dragon."""

    success: bool
    reason: str = ""                    # "no_dragon" | "unknown" | "not_enough"
    upgrade_key: Optional[str] = None
    dragon: Optional[Dragon] = None     # state after the upgrade
    spent: dict = field(default_factory=dict)   # {"meat": n, "fish": n}
    missing: dict = field(default_factory=dict)  # what was lacking, if any
    gains: dict = field(default_factory=dict)    # {"max_hp": 20, ...}


class UpgradeService:
    def __init__(
        self,
        dragons: Optional[DragonRepository] = None,
        players: Optional[PlayerRepository] = None,
        storage: Optional[ColdStorageService] = None,
    ) -> None:
        self.dragons = dragons or DragonRepository()
        self.players = players or PlayerRepository()
        self.storage = storage or ColdStorageService(self.players)

    # --- reading -----------------------------------------------------------
    def available(self) -> dict[str, dict]:
        """All configured upgrades (key -> definition)."""
        return UPGRADES

    def affordable(self, owner_id: int, upgrade_key: str) -> bool:
        """Whether the owner currently has enough food for this upgrade."""
        spec = UPGRADES.get(upgrade_key)
        if spec is None:
            return False
        contents = self.storage.contents(owner_id)
        return all(
            getattr(contents, res, 0) >= amount
            for res, amount in spec["cost"].items()
        )

    def missing_for(self, owner_id: int, upgrade_key: str) -> dict:
        """How much food is still needed for this upgrade ({} if affordable)."""
        spec = UPGRADES.get(upgrade_key)
        if spec is None:
            return {}
        contents = self.storage.contents(owner_id)
        missing = {}
        for res, amount in spec["cost"].items():
            short = amount - getattr(contents, res, 0)
            if short > 0:
                missing[res] = short
        return missing

    # --- applying ----------------------------------------------------------
    def apply(self, owner_id: int, dragon_id: int, upgrade_key: str) -> UpgradeResult:
        """Upgrade one dragon owned by ``owner_id``.

        Ownership is enforced, so an upgrade can never touch another dragon or
        another player's dragon.
        """
        spec = UPGRADES.get(upgrade_key)
        if spec is None:
            return UpgradeResult(success=False, reason="unknown")

        with get_db() as conn:
            dragon = self.dragons.get_owned(dragon_id, owner_id, conn=conn)
            if dragon is None:
                return UpgradeResult(success=False, reason="no_dragon")

            # Check affordability up-front so we never half-spend.
            contents = self.storage.contents(owner_id)
            missing = {
                res: amount - getattr(contents, res, 0)
                for res, amount in spec["cost"].items()
                if amount - getattr(contents, res, 0) > 0
            }
            if missing:
                return UpgradeResult(
                    success=False, reason="not_enough",
                    upgrade_key=upgrade_key, dragon=dragon, missing=missing,
                )

            spent: dict[str, int] = {}
            for res, amount in spec["cost"].items():
                if amount <= 0:
                    continue
                if not self.storage.consume(owner_id, res, amount, conn=conn):
                    # Lost a race against another spend — nothing else applied.
                    return UpgradeResult(
                        success=False, reason="not_enough",
                        upgrade_key=upgrade_key, dragon=dragon,
                        missing={res: amount},
                    )
                spent[res] = amount

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
            else:  # pragma: no cover - guarded by config review
                return UpgradeResult(success=False, reason="unknown")

            self.dragons.update_growth(
                dragon.id, level=level, xp=xp, hp=hp, max_hp=max_hp,
                power=power, conn=conn,
            )
            updated = self.dragons.get(dragon.id, conn=conn)

        return UpgradeResult(
            success=True, upgrade_key=upgrade_key, dragon=updated,
            spent=spent, gains=gains,
        )


def upgrade_display(upgrade_key: str) -> tuple[str, str]:
    """Return (emoji, persian_name) for an upgrade."""
    spec = UPGRADES[upgrade_key]
    return spec["emoji"], spec["name"]
