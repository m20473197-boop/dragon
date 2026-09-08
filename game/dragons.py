"""Dragon management & growth rules (no Telegram code here).

Responsibilities:

* create newborn dragons from hatched eggs,
* rename a dragon,
* award XP and resolve level-ups (max HP / power increases and HP restore).

The leveling math is intentionally simple so the future combat system can
grant XP through the same :meth:`DragonService.add_xp` entry point:

* XP needed to go from ``level`` to ``level + 1`` is
  ``level * XP_PER_LEVEL_BASE`` (1->2 costs 100, 2->3 costs 200, ...).
* Each level grants ``LEVEL_UP_MAX_HP_BONUS`` max HP and
  ``LEVEL_UP_POWER_BONUS`` power, and fully restores HP.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from config import (
    DEFAULT_DRAGON_NAME,
    DRAGON_DEFAULT_HP,
    DRAGON_DEFAULT_HUNGER,
    DRAGON_DEFAULT_LEVEL,
    DRAGON_DEFAULT_MAX_HP,
    DRAGON_DEFAULT_POWER,
    DRAGON_DEFAULT_XP,
    DRAGON_TYPES,
    HUNGER_DECAY_PER_HOUR,
    HUNGER_LOW_THRESHOLD,
    HUNGER_MIN_POWER_FACTOR,
    LEVEL_UP_MAX_HP_BONUS,
    LEVEL_UP_POWER_BONUS,
    XP_PER_LEVEL_BASE,
)
from database.connection import get_db
from models.dragon import Dragon, DragonRepository


def xp_required_for_level(level: int) -> int:
    """XP required to advance from ``level`` to ``level + 1``."""
    return level * XP_PER_LEVEL_BASE


def current_hunger(dragon: Dragon, now: float) -> int:
    """Effective hunger 0..100 after applying time-based decay.

    Hunger is stored at full (100) on birth/feeding with a ``last_fed_time``;
    it decays over time. Legacy rows without a timestamp are treated as full.
    """
    if dragon.last_fed_time is None:
        return DRAGON_DEFAULT_HUNGER
    hours = (now - dragon.last_fed_time) / 3600.0
    decayed = DRAGON_DEFAULT_HUNGER - hours * HUNGER_DECAY_PER_HOUR
    return int(max(0, min(DRAGON_DEFAULT_HUNGER, round(decayed))))


def effective_power(base_power: int, hunger: int) -> int:
    """Actual attack power for a given hunger.

    At/above ``HUNGER_LOW_THRESHOLD`` the dragon fights at full base power;
    below it power scales down linearly to ``HUNGER_MIN_POWER_FACTOR`` (50%)
    at 0 hunger. This does not change the stored stat — it is the combat-ready
    value the future battle system will use.
    """
    if hunger >= HUNGER_LOW_THRESHOLD:
        return base_power
    # Linear ramp from 50% (hunger 0) to 100% (hunger = threshold).
    factor = HUNGER_MIN_POWER_FACTOR + (
        (1.0 - HUNGER_MIN_POWER_FACTOR) * (hunger / HUNGER_LOW_THRESHOLD)
    )
    return int(round(base_power * factor))


def anchor_last_fed_time(hunger_after: int, now: float) -> float:
    """The ``last_fed_time`` that makes hunger decay to ``hunger_after`` at ``now``.

    Because :func:`current_hunger` derives hunger from the time elapsed since
    the last feeding, a feed that only *partially* fills the dragon must move
    that anchor into the past by the time it takes hunger to decay from full
    (100) down to the new level. This keeps the single time-based source of
    truth consistent with the hunger value reported right after feeding.
    """
    hunger_after = max(0, min(DRAGON_DEFAULT_HUNGER, hunger_after))
    missing = DRAGON_DEFAULT_HUNGER - hunger_after
    hours_decayed = missing / HUNGER_DECAY_PER_HOUR if HUNGER_DECAY_PER_HOUR else 0
    return now - hours_decayed * 3600.0


@dataclass
class LevelUpEvent:
    """A single level gained by a dragon (used to build announcements)."""

    dragon_id: int
    name: str
    new_level: int
    max_hp_gained: int
    power_gained: int


@dataclass
class XpResult:
    """Outcome of awarding XP to one dragon."""

    dragon: Dragon
    xp_added: int
    level_ups: list[LevelUpEvent] = field(default_factory=list)

    @property
    def leveled_up(self) -> bool:
        return bool(self.level_ups)


class DragonService:
    def __init__(self, dragons: Optional[DragonRepository] = None) -> None:
        self.dragons = dragons or DragonRepository()

    # --- creation ----------------------------------------------------------
    def create_newborn(
        self,
        owner_id: int,
        dragon_type: str,
        from_egg_id: Optional[int] = None,
        now: Optional[float] = None,
        conn=None,
    ) -> Dragon:
        """Create a level-1 dragon with default stats for its owner."""
        import time

        if dragon_type not in DRAGON_TYPES:
            raise ValueError(f"Unknown dragon type: {dragon_type!r}")
        now = now if now is not None else time.time()
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
            hunger=DRAGON_DEFAULT_HUNGER,
            last_fed_time=now,
            conn=conn,
        )

    # --- reading -----------------------------------------------------------
    def list_for_owner(self, owner_id: int) -> list[Dragon]:
        return self.dragons.list_by_owner(owner_id)

    def count_for_owner(self, owner_id: int) -> int:
        return self.dragons.count_by_owner(owner_id)

    def newest_for_owner(self, owner_id: int) -> Optional[Dragon]:
        """The owner's most recently hatched dragon, or None."""
        dragons = self.dragons.list_by_owner(owner_id)
        return dragons[0] if dragons else None

    # --- naming ------------------------------------------------------------
    def rename(
        self, owner_id: int, dragon_id: int, name: str, conn=None
    ) -> Optional[Dragon]:
        """Rename a dragon owned by ``owner_id``.

        Returns the updated dragon, or ``None`` if the caller does not own it.
        """
        name = name.strip()
        if not self.dragons.set_name(dragon_id, owner_id, name, conn=conn):
            return None
        return self.dragons.get_owned(dragon_id, owner_id, conn=conn)

    # --- XP / leveling -----------------------------------------------------
    def add_xp(self, dragon_id: int, xp_amount: int) -> Optional[XpResult]:
        """Award XP to a dragon and resolve any level-ups atomically.

        Returns the :class:`XpResult`, or ``None`` if the dragon does not
        exist. The whole gain (possibly spanning several levels) is persisted
        in one transaction.
        """
        if xp_amount <= 0:
            dragon = self.dragons.get(dragon_id)
            return None if dragon is None else XpResult(dragon=dragon, xp_added=0)

        with get_db() as conn:
            dragon = self.dragons.get(dragon_id, conn=conn)
            if dragon is None:
                return None

            level_ups: list[LevelUpEvent] = []
            xp = dragon.xp + xp_amount
            level = dragon.level
            max_hp = dragon.max_hp
            power = dragon.power

            # Resolve all level-ups contained in this XP grant.
            while xp >= xp_required_for_level(level):
                xp -= xp_required_for_level(level)
                level += 1
                max_hp += LEVEL_UP_MAX_HP_BONUS
                power += LEVEL_UP_POWER_BONUS
                level_ups.append(
                    LevelUpEvent(
                        dragon_id=dragon.id,
                        name=dragon.name,
                        new_level=level,
                        max_hp_gained=LEVEL_UP_MAX_HP_BONUS,
                        power_gained=LEVEL_UP_POWER_BONUS,
                    )
                )

            # On any level-up the dragon is healed to the new max HP.
            hp = max_hp if level_ups else dragon.hp

            self.dragons.update_growth(
                dragon.id,
                level=level,
                xp=xp,
                hp=hp,
                max_hp=max_hp,
                power=power,
                conn=conn,
            )
            updated = self.dragons.get(dragon_id, conn=conn)

        return XpResult(dragon=updated, xp_added=xp_amount, level_ups=level_ups)


def dragon_type_display(dragon_type: str) -> tuple[str, str]:
    """Return (emoji, persian_name) for a dragon type — e.g. ("🔥", "اژدهای آتشین")."""
    info = DRAGON_TYPES[dragon_type]
    return info["emoji"], info["name"]
