"""Dragon breeding rules — 🧬 آیین پیوند اژدها (Version 9). No Telegram code.

Two of a player's own dragons are combined into a new one. The system reuses
the **existing** rarity and element systems (:mod:`game.rarity`) rather than
inventing a parallel one: a bred dragon is an ordinary row in ``dragons`` and
every existing screen, the arena, feeding and upgrades all treat it normally.

Flow
----
1. :meth:`BreedingService.preview` validates a pair and prices it.
2. :meth:`BreedingService.start` charges ✨ اتر and locks both parents.
3. :meth:`BreedingService.collect_due` runs from a sweep job when the timer
   elapses, creates the child and releases the parents.

Safety
------
* Parents are locked with a guarded ``UPDATE ... WHERE breeding_status='idle'``
  that must affect *both* rows, so a double tap cannot start two rituals.
* The aether charge and the lock happen in one transaction; if the lock fails
  the payment is refunded in the same transaction.
* Completion is guarded too, so a child can never be created twice.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Optional, Sequence

from config import (
    BREEDING_CHILD_NAME_PREFIX,
    BREEDING_COST_BY_RARITY,
    BREEDING_DURATION_SECONDS,
    BREEDING_HYBRIDS,
    BREEDING_MATCHED_PAIR_MULTIPLIER,
    BREEDING_MIN_DRAGONS,
    BREEDING_MIN_LEVEL,
    BREEDING_MUTATION_HP_BONUS,
    BREEDING_MUTATION_POWER_BONUS,
    BREEDING_OUTCOME_HYBRID,
    BREEDING_OUTCOME_INHERIT,
    BREEDING_OUTCOME_MUTATION,
    DRAGON_DEFAULT_HUNGER,
    DRAGON_TYPES,
    RARITIES,
)
from database.connection import get_db
from game.dragons import DragonService
from game.rarity import (
    element_display,
    normalise_rarity,
    rarity_order,
    scaled_stats,
)
from models.breeding import Breeding, BreedingRepository
from models.dragon import Dragon, DragonRepository
from models.player import PlayerRepository
from utils.rng import weighted_choice

logger = logging.getLogger(__name__)

AETHER_COLUMN = "aether"

# Failure reasons (handlers map these to Persian text).
REASON_NOT_ENOUGH_DRAGONS = "not_enough_dragons"
REASON_SAME_DRAGON = "same_dragon"
REASON_NOT_OWNED = "not_owned"
REASON_TOO_LOW_LEVEL = "too_low_level"
REASON_BUSY = "busy"
REASON_ALREADY_BREEDING = "already_breeding"
REASON_NOT_ENOUGH_AETHER = "not_enough_aether"
REASON_LOCK_FAILED = "lock_failed"

# Outcome kinds.
OUTCOME_INHERIT = "inherit"
OUTCOME_HYBRID = "hybrid"
OUTCOME_MUTATION = "mutation"

_RARITY_LADDER: tuple[str, ...] = tuple(
    sorted(RARITIES, key=lambda k: RARITIES[k]["order"])
)


# --- pricing ----------------------------------------------------------------
def rarity_cost(rarity: str) -> int:
    """✨ اتر cost contributed by one parent of the given rarity."""
    return BREEDING_COST_BY_RARITY.get(
        normalise_rarity(rarity), BREEDING_COST_BY_RARITY["normal"]
    )


def pair_cost(rarity_a: str, rarity_b: str) -> int:
    """Total ✨ اتر for a pair.

    The base price is the cost of the *rarest* parent, so a pair of a given
    rarity costs exactly what the config table says (⚪+⚪ = 5, 🟢+🟢 = 10).
    When **both** parents are 🟢 کمیاب or better the ritual costs a premium on
    top, which is what makes breeding two rare dragons more expensive than
    pairing a rare one with a common one.
    """
    a, b = normalise_rarity(rarity_a), normalise_rarity(rarity_b)
    base = max(rarity_cost(a), rarity_cost(b))
    both_rare = min(rarity_order(a), rarity_order(b)) >= rarity_order("rare")
    if both_rare:
        base = int(round(base * BREEDING_MATCHED_PAIR_MULTIPLIER))
    return max(1, base)


# --- element / rarity genetics ----------------------------------------------
def hybrid_for(type_a: str, type_b: str) -> Optional[str]:
    """The hybrid element for a parent pair, or None if they have no hybrid."""
    if type_a == type_b:
        return None
    return BREEDING_HYBRIDS.get(frozenset({type_a, type_b}))


def bump_rarity(rarity: str, steps: int = 1) -> str:
    """Move up the rarity ladder, clamped at 🟡 اسطوره‌ای."""
    current = normalise_rarity(rarity)
    index = _RARITY_LADDER.index(current)
    return _RARITY_LADDER[min(len(_RARITY_LADDER) - 1, index + steps)]


def best_rarity(rarity_a: str, rarity_b: str) -> str:
    """The rarer of two rarities."""
    return rarity_a if rarity_order(rarity_a) >= rarity_order(rarity_b) else rarity_b


def roll_outcome(rng: Optional[random.Random] = None) -> str:
    """70% inherit / 25% hybrid / 5% mutation."""
    rng = rng or random
    return weighted_choice(
        {
            OUTCOME_INHERIT: BREEDING_OUTCOME_INHERIT,
            OUTCOME_HYBRID: BREEDING_OUTCOME_HYBRID,
            OUTCOME_MUTATION: BREEDING_OUTCOME_MUTATION,
        },
        rng=rng,
    )


@dataclass
class ChildBlueprint:
    """What a ritual will produce, before it is written to the database."""

    dragon_type: str
    rarity: str
    outcome: str
    max_hp: int
    power: int
    mutated: bool = False


def child_name(dragon_type: str) -> str:
    """A generated name for a newborn, e.g. «نوزاد گدازه»."""
    _emoji, element = element_display(dragon_type)
    return f"{BREEDING_CHILD_NAME_PREFIX} {element}"


def plan_child(
    parent_a: Dragon,
    parent_b: Dragon,
    rng: Optional[random.Random] = None,
    outcome: Optional[str] = None,
) -> ChildBlueprint:
    """Decide the child's element, rarity and starting stats.

    ``outcome`` can be forced for testing; otherwise it is rolled. A hybrid
    outcome falls back to inheritance when the parents have no hybrid pairing
    configured, so the player always gets a sensible dragon.
    """
    rng = rng or random
    outcome = outcome or roll_outcome(rng)

    top = best_rarity(parent_a.rarity, parent_b.rarity)
    mutated = False

    if outcome == OUTCOME_MUTATION:
        # A mutation is always rarer than the best parent.
        dragon_type = hybrid_for(parent_a.dragon_type, parent_b.dragon_type)
        if dragon_type is None:
            dragon_type = rng.choice([parent_a.dragon_type, parent_b.dragon_type])
        rarity = bump_rarity(top, 1)
        mutated = True
    elif outcome == OUTCOME_HYBRID:
        dragon_type = hybrid_for(parent_a.dragon_type, parent_b.dragon_type)
        if dragon_type is None:
            # No hybrid exists for this pairing — inherit instead.
            outcome = OUTCOME_INHERIT
            dragon_type = rng.choice([parent_a.dragon_type, parent_b.dragon_type])
            rarity = _inherit_rarity(parent_a, parent_b, rng)
        else:
            rarity = top
    else:
        dragon_type = rng.choice([parent_a.dragon_type, parent_b.dragon_type])
        rarity = _inherit_rarity(parent_a, parent_b, rng)

    if outcome == OUTCOME_HYBRID:
        rarity = top

    max_hp, power = scaled_stats(rarity)
    if mutated:
        max_hp = int(round(max_hp * (1 + BREEDING_MUTATION_HP_BONUS)))
        power = int(round(power * (1 + BREEDING_MUTATION_POWER_BONUS)))

    return ChildBlueprint(
        dragon_type=dragon_type,
        rarity=rarity,
        outcome=outcome,
        max_hp=max_hp,
        power=power,
        mutated=mutated,
    )


def _inherit_rarity(
    parent_a: Dragon, parent_b: Dragon, rng: random.Random
) -> str:
    """An inherited child takes one parent's rarity (50/50)."""
    return normalise_rarity(
        rng.choice([parent_a.rarity, parent_b.rarity])
    )


# --- results ----------------------------------------------------------------
@dataclass
class BreedingPreview:
    ok: bool
    reason: Optional[str] = None
    parent_a: Optional[Dragon] = None
    parent_b: Optional[Dragon] = None
    cost: int = 0
    balance: int = 0
    duration: int = BREEDING_DURATION_SECONDS

    @property
    def affordable(self) -> bool:
        return self.balance >= self.cost


@dataclass
class BreedingStart:
    ok: bool
    reason: Optional[str] = None
    breeding: Optional[Breeding] = None
    parent_a: Optional[Dragon] = None
    parent_b: Optional[Dragon] = None
    cost: int = 0
    balance_after: int = 0


@dataclass
class BreedingResult:
    breeding: Breeding
    child: Dragon
    parent_a: Optional[Dragon]
    parent_b: Optional[Dragon]
    outcome: str
    mutated: bool
    owner_id: int
    chat_id: Optional[int]


class BreedingService:
    """Validation, pricing, locking and completion of breeding rituals."""

    def __init__(
        self,
        dragons: Optional[DragonRepository] = None,
        players: Optional[PlayerRepository] = None,
        breedings: Optional[BreedingRepository] = None,
        dragon_service: Optional[DragonService] = None,
    ) -> None:
        self.dragons = dragons or DragonRepository()
        self.players = players or PlayerRepository()
        self.breedings = breedings or BreedingRepository()
        self.dragon_service = dragon_service or DragonService(dragons=self.dragons)

    # --- reads ------------------------------------------------------------
    def balance(self, user_id: int) -> int:
        player = self.players.get(user_id)
        return player.aether if player else 0

    def selectable(self, user_id: int) -> list[Dragon]:
        """Dragons the player may pick: owned and not busy."""
        return self.dragons.list_idle_by_owner(user_id)

    def eligible(self, dragon: Dragon) -> bool:
        """True when a dragon meets the level requirement and is free."""
        return (
            dragon.level >= BREEDING_MIN_LEVEL
            and dragon.breeding_status != "breeding"
        )

    def active(self, user_id: int) -> Optional[Breeding]:
        return self.breedings.active_for_owner(user_id)

    # --- validation -------------------------------------------------------
    def preview(
        self, user_id: int, dragon_a_id: int, dragon_b_id: int
    ) -> BreedingPreview:
        """Validate a pair and quote its cost, without changing anything."""
        balance = self.balance(user_id)

        if self.breedings.active_for_owner(user_id) is not None:
            return BreedingPreview(
                ok=False, reason=REASON_ALREADY_BREEDING, balance=balance
            )

        if self.dragons.count_by_owner(user_id) < BREEDING_MIN_DRAGONS:
            return BreedingPreview(
                ok=False, reason=REASON_NOT_ENOUGH_DRAGONS, balance=balance
            )

        if dragon_a_id == dragon_b_id:
            return BreedingPreview(
                ok=False, reason=REASON_SAME_DRAGON, balance=balance
            )

        parent_a = self.dragons.get_owned(dragon_a_id, user_id)
        parent_b = self.dragons.get_owned(dragon_b_id, user_id)
        if parent_a is None or parent_b is None:
            return BreedingPreview(
                ok=False, reason=REASON_NOT_OWNED, balance=balance
            )

        if parent_a.breeding_status == "breeding" or parent_b.breeding_status == "breeding":
            return BreedingPreview(
                ok=False, reason=REASON_BUSY, balance=balance,
                parent_a=parent_a, parent_b=parent_b,
            )

        if parent_a.level < BREEDING_MIN_LEVEL or parent_b.level < BREEDING_MIN_LEVEL:
            return BreedingPreview(
                ok=False, reason=REASON_TOO_LOW_LEVEL, balance=balance,
                parent_a=parent_a, parent_b=parent_b,
            )

        cost = pair_cost(parent_a.rarity, parent_b.rarity)
        return BreedingPreview(
            ok=True, parent_a=parent_a, parent_b=parent_b,
            cost=cost, balance=balance,
        )

    # --- starting a ritual -------------------------------------------------
    def start(
        self,
        user_id: int,
        dragon_a_id: int,
        dragon_b_id: int,
        chat_id: Optional[int] = None,
        now: Optional[float] = None,
    ) -> BreedingStart:
        """Charge the aether, lock both parents and open the ritual."""
        now = now if now is not None else time.time()
        preview = self.preview(user_id, dragon_a_id, dragon_b_id)
        if not preview.ok:
            return BreedingStart(ok=False, reason=preview.reason, cost=preview.cost)

        cost = preview.cost
        finish = now + BREEDING_DURATION_SECONDS

        with get_db() as conn:
            # Pay first: the guarded UPDATE refuses to go negative.
            if not self.players.spend_currency(
                user_id, AETHER_COLUMN, cost, conn=conn
            ):
                return BreedingStart(
                    ok=False, reason=REASON_NOT_ENOUGH_AETHER, cost=cost
                )

            # Lock both parents; this must affect exactly two rows.
            locked = self.dragons.mark_breeding(
                (dragon_a_id, dragon_b_id), user_id, finish, conn=conn
            )
            if not locked:
                # Someone else locked one of them first — refund in the same
                # transaction so no aether is ever lost.
                self.players.add_resources(user_id, aether=cost, conn=conn)
                return BreedingStart(
                    ok=False, reason=REASON_LOCK_FAILED, cost=cost
                )

            breeding = self.breedings.create(
                owner_id=user_id,
                parent1_id=dragon_a_id,
                parent2_id=dragon_b_id,
                start_time=now,
                finish_time=finish,
                cost=cost,
                chat_id=chat_id,
                conn=conn,
            )

        return BreedingStart(
            ok=True,
            breeding=breeding,
            parent_a=preview.parent_a,
            parent_b=preview.parent_b,
            cost=cost,
            balance_after=self.balance(user_id),
        )

    # --- completion --------------------------------------------------------
    def collect_due(
        self,
        now: Optional[float] = None,
        rng: Optional[random.Random] = None,
    ) -> list[BreedingResult]:
        """Finish every ritual whose timer elapsed. Safe to call repeatedly."""
        now = now if now is not None else time.time()
        rng = rng or random
        results: list[BreedingResult] = []

        for breeding in self.breedings.find_due(now):
            try:
                result = self._finish(breeding, rng)
            except Exception:  # pragma: no cover - never break the sweep
                logger.exception(
                    "Could not finish breeding %s", breeding.breeding_id
                )
                continue
            if result is not None:
                results.append(result)
        return results

    def _finish(
        self, breeding: Breeding, rng: random.Random
    ) -> Optional[BreedingResult]:
        parent_a = self.dragons.get(breeding.parent1_id)
        parent_b = self.dragons.get(breeding.parent2_id)

        if parent_a is None or parent_b is None:
            # A parent vanished (admin reset): release and close it out.
            self.dragons.clear_breeding(breeding.parents)
            self.breedings.cancel(breeding.breeding_id)
            return None

        blueprint = plan_child(parent_a, parent_b, rng=rng)

        with get_db() as conn:
            # Guarded: only the first sweep to claim this ritual creates a child.
            if not self.breedings.complete(
                breeding.breeding_id, child_id=-1,
                outcome=blueprint.outcome, conn=conn,
            ):
                return None

            child = self.dragons.create(
                owner_id=breeding.owner_id,
                dragon_type=blueprint.dragon_type,
                from_egg_id=None,
                name=child_name(blueprint.dragon_type),
                level=1,
                xp=0,
                hp=blueprint.max_hp,
                max_hp=blueprint.max_hp,
                power=blueprint.power,
                hunger=DRAGON_DEFAULT_HUNGER,
                rarity=blueprint.rarity,
                parent_dragon_1=parent_a.id,
                parent_dragon_2=parent_b.id,
                last_fed_time=time.time(),
                conn=conn,
            )
            # Record the real child id now that it exists.
            conn.execute(
                "UPDATE breedings SET child_id = ? WHERE breeding_id = ?",
                (child.id, breeding.breeding_id),
            )
            # Parents are free again.
            self.dragons.clear_breeding(breeding.parents, conn=conn)
            # The player's dragon counter follows the existing convention.
            self.players.add_resources(breeding.owner_id, dragons=1, conn=conn)
            # A first dragon always becomes active (matches the egg system).
            if self.players.get_active_dragon_id(breeding.owner_id, conn=conn) is None:
                self.players.set_active_dragon(
                    breeding.owner_id, child.id, conn=conn
                )

        return BreedingResult(
            breeding=breeding,
            child=child,
            parent_a=parent_a,
            parent_b=parent_b,
            outcome=blueprint.outcome,
            mutated=blueprint.mutated,
            owner_id=breeding.owner_id,
            chat_id=breeding.chat_id,
        )

    def cancel(self, user_id: int) -> bool:
        """Abandon the owner's active ritual and free the parents (no refund)."""
        breeding = self.breedings.active_for_owner(user_id)
        if breeding is None:
            return False
        with get_db() as conn:
            if not self.breedings.cancel(breeding.breeding_id, conn=conn):
                return False
            self.dragons.clear_breeding(breeding.parents, conn=conn)
        return True


def hybrid_pairs() -> list[tuple[str, str, str]]:
    """All configured hybrid combinations as ``(parent_a, parent_b, child)``."""
    pairs: list[tuple[str, str, str]] = []
    for combo, child in BREEDING_HYBRIDS.items():
        a, b = sorted(combo)
        if a in DRAGON_TYPES and b in DRAGON_TYPES and child in DRAGON_TYPES:
            pairs.append((a, b, child))
    return sorted(pairs)


def describe_parents(parents: Sequence[Dragon]) -> str:
    """Compact «🔥 آذر + ❄️ یخ» summary used in messages."""
    parts = []
    for dragon in parents:
        emoji, _ = element_display(dragon.dragon_type)
        parts.append(f"{emoji} {dragon.name}")
    return " + ".join(parts)
