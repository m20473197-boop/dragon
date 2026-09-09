"""Dragon feeding rules (no Telegram code here).

Feeding consumes food from the player's storage, heals the dragon, grants XP
and restores hunger. The whole operation runs in one transaction and the
resource cost is checked with an atomic, guarded UPDATE, so rapid/double taps
can never spend more food than the player actually has.

Feeding is reached only from the dragon profile page («اژدها» ->
select a dragon -> «🥩 غذا دادن»); there is no feeding command. Food is spent
one unit at a time (see config.FOOD_UNITS), either a single unit or exactly as
many as the dragon needs to become full.

Hunger decays over time (see game.dragons.current_hunger); a well-fed dragon
fights at full power while a hungry one is weaker (effective_power).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from config import DRAGON_DEFAULT_HUNGER, FOODS, FOOD_PRIORITY, FOOD_UNITS, FULL_FEED_MAX_UNITS
from config import LEVEL_UP_MAX_HP_BONUS, LEVEL_UP_POWER_BONUS
from database.connection import get_db
from game.dragons import anchor_last_fed_time, current_hunger, xp_required_for_level
from game.storage import ColdStorageService
from models.dragon import Dragon, DragonRepository
from models.player import PlayerRepository


@dataclass
class UnitFeedResult:
    """Outcome of profile-page feeding (one unit, or feeding until full)."""

    success: bool
    reason: str = ""                      # "no_dragon" | "no_food" | "full"
    food_key: Optional[str] = None        # food used for a single-unit feed
    units: int = 0                        # how many food units were consumed
    spent: dict = field(default_factory=dict)  # {food_key: units} for full feed
    dragon: Optional[Dragon] = None       # dragon state after feeding
    hunger_before: int = 0
    hunger_after: int = 0
    hp_healed: int = 0
    xp_added: int = 0
    levels_gained: int = 0


class FeedingService:
    def __init__(
        self,
        dragons: Optional[DragonRepository] = None,
        players: Optional[PlayerRepository] = None,
        storage: Optional[ColdStorageService] = None,
    ) -> None:
        self.dragons = dragons or DragonRepository()
        # Food always comes out of the player's cold storage (سردخانه).
        self.storage = storage or ColdStorageService(players)

    def food_count(self, owner_id: int, food_key: str) -> int:
        """How much of the given food is in the owner's cold storage."""
        return self.storage.count(owner_id, FOODS[food_key]["resource"])

    # --- profile-page feeding (single unit / fill up) ----------------------
    def feed_unit(
        self,
        owner_id: int,
        dragon_id: int,
        food_key: Optional[str] = None,
        now: Optional[float] = None,
    ) -> "UnitFeedResult":
        """Feed ONE unit of food to one specific dragon.

        ``food_key`` picks the food; when omitted the first available food in
        ``FOOD_PRIORITY`` is used. One unit is removed from the owner's cold
        storage and the dragon gains hunger, HP (if hurt) and XP per
        ``config.FOOD_UNITS``.
        """
        now = now if now is not None else time.time()
        with get_db() as conn:
            dragon = self.dragons.get_owned(dragon_id, owner_id, conn=conn)
            if dragon is None:
                return UnitFeedResult(success=False, reason="no_dragon")
            # V9: a dragon locked in a 🧬 breeding ritual cannot be fed.
            if dragon.breeding_status == "breeding":
                return UnitFeedResult(success=False, reason="busy", dragon=dragon)

            hunger_before = current_hunger(dragon, now)
            if hunger_before >= DRAGON_DEFAULT_HUNGER:
                return UnitFeedResult(
                    success=False, reason="full", hunger_before=hunger_before,
                    hunger_after=hunger_before, dragon=dragon,
                )

            key = self._pick_food(owner_id, food_key, conn=conn)
            if key is None:
                return UnitFeedResult(success=False, reason="no_food",
                                      hunger_before=hunger_before)

            if not self.storage.consume(owner_id, FOODS[key]["resource"], 1, conn=conn):
                return UnitFeedResult(success=False, reason="no_food",
                                      hunger_before=hunger_before)

            unit = FOOD_UNITS[key]
            dragon, gained = self._apply_unit(
                dragon, unit, hunger_before, now, conn=conn
            )

        return UnitFeedResult(
            success=True,
            food_key=key,
            units=1,
            dragon=dragon,
            hunger_before=hunger_before,
            hunger_after=gained["hunger_after"],
            hp_healed=gained["hp_healed"],
            xp_added=gained["xp_added"],
            levels_gained=gained["levels_gained"],
        )

    def feed_until_full(
        self,
        owner_id: int,
        dragon_id: int,
        now: Optional[float] = None,
    ) -> "UnitFeedResult":
        """Feed exactly as many units as the dragon needs to reach full hunger.

        Consumes only what is required (never more), stops early when the cold
        storage runs out, and reports how much of each food was used.
        """
        now = now if now is not None else time.time()
        spent: dict[str, int] = {}
        total_hp = total_xp = total_levels = 0

        with get_db() as conn:
            dragon = self.dragons.get_owned(dragon_id, owner_id, conn=conn)
            if dragon is None:
                return UnitFeedResult(success=False, reason="no_dragon")
            # V9: a dragon locked in a 🧬 breeding ritual cannot be fed.
            if dragon.breeding_status == "breeding":
                return UnitFeedResult(success=False, reason="busy", dragon=dragon)

            hunger_before = current_hunger(dragon, now)
            if hunger_before >= DRAGON_DEFAULT_HUNGER:
                return UnitFeedResult(
                    success=False, reason="full", dragon=dragon,
                    hunger_before=hunger_before, hunger_after=hunger_before,
                )

            hunger = hunger_before
            for _ in range(FULL_FEED_MAX_UNITS):
                if hunger >= DRAGON_DEFAULT_HUNGER:
                    break
                key = self._pick_food(owner_id, None, conn=conn)
                if key is None:
                    break  # storage empty; keep whatever was already fed
                if not self.storage.consume(
                    owner_id, FOODS[key]["resource"], 1, conn=conn
                ):
                    break
                unit = FOOD_UNITS[key]
                dragon, gained = self._apply_unit(dragon, unit, hunger, now, conn=conn)
                hunger = gained["hunger_after"]
                spent[key] = spent.get(key, 0) + 1
                total_hp += gained["hp_healed"]
                total_xp += gained["xp_added"]
                total_levels += gained["levels_gained"]

        if not spent:
            return UnitFeedResult(
                success=False, reason="no_food", dragon=dragon,
                hunger_before=hunger_before, hunger_after=hunger_before,
            )

        return UnitFeedResult(
            success=True,
            units=sum(spent.values()),
            spent=spent,
            dragon=dragon,
            hunger_before=hunger_before,
            hunger_after=hunger,
            hp_healed=total_hp,
            xp_added=total_xp,
            levels_gained=total_levels,
        )

    # --- internals ---------------------------------------------------------
    def _pick_food(self, owner_id: int, food_key: Optional[str], conn=None) -> Optional[str]:
        """Choose which food to spend: the requested one, else the first stored."""
        candidates = (food_key,) if food_key else FOOD_PRIORITY
        for key in candidates:
            if key not in FOODS:
                continue
            if self.storage.count(owner_id, FOODS[key]["resource"]) > 0:
                return key
        return None

    def _apply_unit(self, dragon, unit: dict, hunger_before: int, now: float, conn):
        """Apply one food unit's hunger/HP/XP to a dragon and persist it."""
        hunger_after = min(DRAGON_DEFAULT_HUNGER, hunger_before + unit["hunger"])
        fed_time = anchor_last_fed_time(hunger_after, now)

        xp = dragon.xp + unit["xp"]
        level, max_hp, power = dragon.level, dragon.max_hp, dragon.power
        levels_gained = 0
        while xp >= xp_required_for_level(level):
            xp -= xp_required_for_level(level)
            level += 1
            max_hp += LEVEL_UP_MAX_HP_BONUS
            power += LEVEL_UP_POWER_BONUS
            levels_gained += 1

        if levels_gained > 0:
            hp = max_hp
            hp_healed = max_hp - dragon.hp
        else:
            hp = min(max_hp, dragon.hp + unit["hp"])
            hp_healed = hp - dragon.hp

        self.dragons.update_full_stats(
            dragon.id, level=level, xp=xp, hp=hp, max_hp=max_hp, power=power,
            hunger=hunger_after, last_fed_time=fed_time, conn=conn,
        )
        updated = self.dragons.get(dragon.id, conn=conn)
        return updated, {
            "hunger_after": hunger_after,
            "hp_healed": hp_healed,
            "xp_added": unit["xp"],
            "levels_gained": levels_gained,
        }


def food_display(food_key: str) -> tuple[str, str]:
    """Return (emoji, persian_name) for a food type."""
    info = FOODS[food_key]
    return info["emoji"], info["name"]
