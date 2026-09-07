"""Dragon management rules (no Telegram code here).

Owns creating newborn dragons from hatched eggs and reading a player's
dragons. Stats/levelling/combat are intentionally minimal for now: every
dragon is born with the default stats from ``config`` and the random type is
chosen by the egg's rarity pool in :class:`game.eggs.EggService`.
"""
from __future__ import annotations

from typing import Optional

from config import (
    DEFAULT_DRAGON_NAME,
    DRAGON_DEFAULT_HP,
    DRAGON_DEFAULT_LEVEL,
    DRAGON_DEFAULT_MAX_HP,
    DRAGON_DEFAULT_POWER,
    DRAGON_DEFAULT_XP,
    DRAGON_TYPES,
)
from models.dragon import Dragon, DragonRepository


class DragonService:
    def __init__(self, dragons: Optional[DragonRepository] = None) -> None:
        self.dragons = dragons or DragonRepository()

    def create_newborn(
        self,
        owner_id: int,
        dragon_type: str,
        from_egg_id: Optional[int] = None,
        conn=None,
    ) -> Dragon:
        """Create a level-1 dragon with default stats for its owner."""
        if dragon_type not in DRAGON_TYPES:
            raise ValueError(f"Unknown dragon type: {dragon_type!r}")
        return self.dragons.create(
            owner_id=owner_id,
            dragon_type=dragon_type,
            from_egg_id=from_egg_id,
            name=DEFAULT_DRAGON_NAME,
            level=DRAGON_DEFAULT_LEVEL,
            xp=DRAGON_DEFAULT_XP,
            hp=DRAGON_DEFAULT_HP,
            max_hp=DRAGON_DEFAULT_MAX_HP,
            power=DRAGON_DEFAULT_POWER,
            conn=conn,
        )

    def list_for_owner(self, owner_id: int) -> list[Dragon]:
        return self.dragons.list_by_owner(owner_id)

    def count_for_owner(self, owner_id: int) -> int:
        return self.dragons.count_by_owner(owner_id)


def dragon_type_display(dragon_type: str) -> tuple[str, str]:
    """Return (emoji, persian_name) for a dragon type — e.g. ("🔥", "اژدهای آتشین")."""
    info = DRAGON_TYPES[dragon_type]
    return info["emoji"], info["name"]
