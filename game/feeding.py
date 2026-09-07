"""Dragon feeding rules (no Telegram code here).

Feeding consumes food from the player's storage, heals the dragon, grants XP
and restores hunger. The whole operation runs in one transaction and the
resource cost is checked with an atomic, guarded UPDATE, so rapid/double taps
can never spend more food than the player actually has.

* Meat: consumes 3 🥩 meat  -> +hunger, +HP, +XP.
* Fish: consumes 5 🐟 fish  -> +hunger, +HP, +XP.

Hunger decays over time (see game.dragons.current_hunger); a well-fed dragon
fights at full power while a hungry one is weaker (effective_power).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from config import DRAGON_DEFAULT_HUNGER, FOODS
from database.connection import get_db
from game.dragons import xp_required_for_level
from config import LEVEL_UP_MAX_HP_BONUS, LEVEL_UP_POWER_BONUS
from models.dragon import Dragon, DragonRepository
from models.player import PlayerRepository


@dataclass
class FeedResult:
    """Outcome of feeding a dragon."""

    success: bool
    reason: str = ""                      # "no_dragon" | "not_enough"
    food_key: Optional[str] = None
    dragon: Optional[Dragon] = None       # dragon state after feeding
    hp_healed: int = 0
    xp_added: int = 0
    hunger_before: int = 0
    hunger_after: int = 0
    levels_gained: int = 0


class FeedingService:
    def __init__(
        self,
        dragons: Optional[DragonRepository] = None,
        players: Optional[PlayerRepository] = None,
    ) -> None:
        self.dragons = dragons or DragonRepository()
        self.players = players or PlayerRepository()

    def food_count(self, owner_id: int, food_key: str) -> int:
        """How much of the given food the owner currently holds."""
        player = self.players.get(owner_id)
        if player is None:
            return 0
        return getattr(player, FOODS[food_key]["resource"], 0)

    def feed(self, owner_id: int, food_key: str, now: Optional[float] = None) -> FeedResult:
        """Feed the owner's newest dragon with one unit of ``food_key``.

        Returns a FeedResult. On insufficient food / no dragon, nothing is
        changed.
        """
        now = now if now is not None else time.time()
        if food_key not in FOODS:
            raise ValueError(f"Unknown food: {food_key!r}")
        food = FOODS[food_key]

        with get_db() as conn:
            dragon = self.dragons.newest_for_owner(owner_id, conn=conn)
            if dragon is None:
                return FeedResult(success=False, reason="no_dragon")

            # Atomically spend the food; the UPDATE only succeeds if enough is
            # stored, so two concurrent feeds cannot both consume it.
            if not self.players.spend_resource(
                owner_id, food["resource"], food["cost"], conn=conn
            ):
                return FeedResult(success=False, reason="not_enough")

            # Compute effective (decayed) hunger before feeding.
            from game.dragons import current_hunger

            hunger_before = current_hunger(dragon, now)
            hunger_after = min(DRAGON_DEFAULT_HUNGER, hunger_before + food["hunger"])

            # Apply XP + level-ups (pure math; same rules as DragonService).
            xp = dragon.xp + food["xp"]
            level = dragon.level
            max_hp = dragon.max_hp
            power = dragon.power
            levels_gained = 0
            while xp >= xp_required_for_level(level):
                xp -= xp_required_for_level(level)
                level += 1
                max_hp += LEVEL_UP_MAX_HP_BONUS
                power += LEVEL_UP_POWER_BONUS
                levels_gained += 1

            # Healing: level-up fully restores HP; otherwise the food heals,
            # capped at max HP.
            if levels_gained > 0:
                hp = max_hp
                hp_healed = max_hp - dragon.hp
            else:
                new_hp = min(max_hp, dragon.hp + food["hp"])
                hp_healed = new_hp - dragon.hp
                hp = new_hp

            self.dragons.update_full_stats(
                dragon.id,
                level=level,
                xp=xp,
                hp=hp,
                max_hp=max_hp,
                power=power,
                hunger=hunger_after,
                last_fed_time=now,
                conn=conn,
            )
            updated = self.dragons.get(dragon.id, conn=conn)

        return FeedResult(
            success=True,
            food_key=food_key,
            dragon=updated,
            hp_healed=hp_healed,
            xp_added=food["xp"],
            hunger_before=hunger_before,
            hunger_after=hunger_after,
            levels_gained=levels_gained,
        )


def food_display(food_key: str) -> tuple[str, str]:
    """Return (emoji, persian_name) for a food type."""
    info = FOODS[food_key]
    return info["emoji"], info["name"]
