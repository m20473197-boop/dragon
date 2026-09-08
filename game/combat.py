"""Basic PvE combat rules (Version 4) — no Telegram code here.

A player fights with their **active dragon** against a randomly chosen enemy
from ``config.ENEMIES``. One round of «⚔️ حمله» is a single exchange:

1. the dragon hits for ``effective_power(power, hunger) + random bonus``,
2. if the enemy survives, it hits back for ``attack_power ± spread``.

Rules that must not change:

* a dragon is **never deleted or lost** — when its HP would reach 0 it is
  clamped to ``BATTLE_DRAGON_MIN_HP`` and the battle counts as a defeat;
* rewards go through the existing currency system (``players.obsidian`` /
  ``players.aether``) and the existing XP system (``DragonService.add_xp``),
  so level-ups behave exactly like everywhere else;
* only one active battle per user, enforced in the database.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from config import (
    BATTLE_AETHER_CHANCE,
    BATTLE_AETHER_MAX,
    BATTLE_AETHER_MIN,
    BATTLE_DAMAGE_BONUS_MAX,
    BATTLE_DAMAGE_BONUS_MIN,
    BATTLE_DRAGON_MIN_HP,
    BATTLE_ENEMY_DAMAGE_SPREAD,
    BATTLE_MIN_DAMAGE,
    BATTLE_MIN_HP_TO_FIGHT,
    BATTLE_STALE_SECONDS,
    ENEMIES,
)
from database.connection import get_db
from game.dragons import DragonService, current_hunger, effective_power
from models.battle import (
    STATUS_FLED,
    STATUS_LOST,
    STATUS_WON,
    Battle,
    BattleRepository,
)
from models.dragon import Dragon, DragonRepository
from models.player import PlayerRepository

logger = logging.getLogger(__name__)


# --- enemies ----------------------------------------------------------------
@dataclass
class Enemy:
    """A runtime view of one ``config.ENEMIES`` entry."""

    enemy_id: str
    name: str
    emoji: str
    hp: int
    max_hp: int
    attack_power: int
    reward_min: int
    reward_max: int
    xp_min: int
    xp_max: int

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}"


def get_enemy(enemy_id: str, hp: Optional[int] = None) -> Optional[Enemy]:
    """Build an :class:`Enemy` from config; ``None`` for an unknown key."""
    spec = ENEMIES.get(enemy_id)
    if spec is None:
        return None
    max_hp = int(spec["max_hp"])
    return Enemy(
        enemy_id=enemy_id,
        name=spec["name"],
        emoji=spec["emoji"],
        hp=max_hp if hp is None else max(0, int(hp)),
        max_hp=max_hp,
        attack_power=int(spec["attack_power"]),
        reward_min=int(spec["reward_min"]),
        reward_max=int(spec["reward_max"]),
        xp_min=int(spec["xp_min"]),
        xp_max=int(spec["xp_max"]),
    )


def random_enemy(rng: Optional[random.Random] = None) -> Enemy:
    """Pick a random enemy, weighted by its ``weight``."""
    rng = rng or random
    keys = list(ENEMIES)
    weights = [max(1, int(ENEMIES[k].get("weight", 1))) for k in keys]
    key = rng.choices(keys, weights=weights, k=1)[0]
    enemy = get_enemy(key)
    assert enemy is not None  # keys come from ENEMIES itself
    return enemy


# --- damage -----------------------------------------------------------------
def roll_dragon_damage(
    dragon: Dragon, now: Optional[float] = None, rng: Optional[random.Random] = None
) -> int:
    """Damage the dragon deals: hunger-adjusted power + a random bonus."""
    rng = rng or random
    now = now if now is not None else time.time()
    hunger = current_hunger(dragon, now)
    power = effective_power(dragon.power, hunger)
    bonus = rng.randint(BATTLE_DAMAGE_BONUS_MIN, BATTLE_DAMAGE_BONUS_MAX)
    return max(BATTLE_MIN_DAMAGE, power + bonus)


def roll_enemy_damage(enemy: Enemy, rng: Optional[random.Random] = None) -> int:
    """Damage the enemy deals: its attack power with a small spread."""
    rng = rng or random
    spread = BATTLE_ENEMY_DAMAGE_SPREAD
    return max(
        BATTLE_MIN_DAMAGE, enemy.attack_power + rng.randint(-spread, spread)
    )


# --- results ----------------------------------------------------------------
@dataclass
class StartResult:
    """Outcome of «مبارزه»."""

    success: bool
    reason: str = ""  # "no_dragon" | "already_fighting" | "too_weak" | "error"
    battle: Optional[Battle] = None
    enemy: Optional[Enemy] = None
    dragon: Optional[Dragon] = None


@dataclass
class AttackResult:
    """Outcome of one «⚔️ حمله» press."""

    success: bool
    reason: str = ""  # "not_found" | "finished" | "not_owner" | "stale" | "error"
    battle: Optional[Battle] = None
    enemy: Optional[Enemy] = None
    dragon: Optional[Dragon] = None
    dragon_damage: int = 0
    enemy_damage: int = 0
    enemy_hp_before: int = 0
    enemy_hp_after: int = 0
    dragon_hp_before: int = 0
    dragon_hp_after: int = 0
    won: bool = False
    lost: bool = False
    rewards: dict = field(default_factory=dict)
    xp_gained: int = 0
    level_ups: list = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.won or self.lost

    @property
    def obsidian(self) -> int:
        return self.rewards.get("obsidian", 0)

    @property
    def aether(self) -> int:
        return self.rewards.get("aether", 0)


@dataclass
class FleeResult:
    success: bool
    reason: str = ""  # "not_found" | "finished" | "not_owner"
    battle: Optional[Battle] = None
    enemy: Optional[Enemy] = None
    dragon: Optional[Dragon] = None


# --- service ----------------------------------------------------------------
class CombatService:
    """All combat operations. Safe to share across chats and users."""

    def __init__(
        self,
        battles: Optional[BattleRepository] = None,
        dragons: Optional[DragonRepository] = None,
        players: Optional[PlayerRepository] = None,
        dragon_service: Optional[DragonService] = None,
    ) -> None:
        self.battles = battles or BattleRepository()
        self.dragons = dragons or DragonRepository()
        self.players = players or PlayerRepository()
        self.dragon_service = dragon_service or DragonService(self.dragons)

    # --- starting ----------------------------------------------------------
    def start_battle(
        self,
        user_id: int,
        chat_id: Optional[int] = None,
        now: Optional[float] = None,
        rng: Optional[random.Random] = None,
    ) -> StartResult:
        """Start a fight with the player's active dragon."""
        now = now if now is not None else time.time()

        try:
            self.players.get_or_create(user_id, None)
            dragon_id = self.players.get_active_dragon_id(user_id)
            if dragon_id is None:
                return StartResult(success=False, reason="no_dragon")

            dragon = self.dragons.get_owned(dragon_id, user_id)
            if dragon is None:
                # Active dragon points at something the user no longer owns.
                self.players.clear_active_dragon_if(user_id, dragon_id)
                return StartResult(success=False, reason="no_dragon")

            # Reclaim battles nobody finished so a user is never stuck.
            self.expire_stale_battles(now=now)

            existing = self.battles.get_active_for_user(user_id)
            if existing is not None:
                return StartResult(
                    success=False,
                    reason="already_fighting",
                    battle=existing,
                    enemy=get_enemy(existing.enemy_id, existing.enemy_hp),
                    dragon=dragon,
                )

            if dragon.hp <= BATTLE_MIN_HP_TO_FIGHT:
                return StartResult(success=False, reason="too_weak", dragon=dragon)

            enemy = random_enemy(rng)
            battle = self.battles.start(
                user_id=user_id,
                dragon_id=dragon.id,
                enemy_id=enemy.enemy_id,
                enemy_hp=enemy.max_hp,
                enemy_max_hp=enemy.max_hp,
                created_time=now,
                chat_id=chat_id,
            )
            if battle is None:
                # Lost the race against a simultaneous «مبارزه».
                current = self.battles.get_active_for_user(user_id)
                return StartResult(
                    success=False,
                    reason="already_fighting",
                    battle=current,
                    enemy=(
                        get_enemy(current.enemy_id, current.enemy_hp)
                        if current else None
                    ),
                    dragon=dragon,
                )
            return StartResult(success=True, battle=battle, enemy=enemy, dragon=dragon)
        except Exception:
            logger.exception("start_battle failed for user %s", user_id)
            return StartResult(success=False, reason="error")

    # --- attacking ---------------------------------------------------------
    def attack(
        self,
        battle_id: int,
        user_id: int,
        now: Optional[float] = None,
        rng: Optional[random.Random] = None,
    ) -> AttackResult:
        """Resolve one exchange: dragon hits, then the enemy hits back."""
        now = now if now is not None else time.time()

        try:
            battle = self.battles.get(battle_id)
            if battle is None:
                return AttackResult(success=False, reason="not_found")
            if battle.user_id != user_id:
                return AttackResult(success=False, reason="not_owner", battle=battle)
            if not battle.is_active:
                return AttackResult(success=False, reason="finished", battle=battle)

            enemy = get_enemy(battle.enemy_id, battle.enemy_hp)
            if enemy is None:
                # Enemy removed from config — close the battle rather than crash.
                self.battles.finish(battle_id, STATUS_FLED, now)
                return AttackResult(success=False, reason="not_found", battle=battle)

            dragon = self.dragons.get_owned(battle.dragon_id, user_id)
            if dragon is None:
                self.battles.finish(battle_id, STATUS_FLED, now)
                return AttackResult(success=False, reason="not_found", battle=battle)

            dragon_damage = roll_dragon_damage(dragon, now=now, rng=rng)
            enemy_hp_before = enemy.hp
            enemy_hp_after = max(0, enemy_hp_before - dragon_damage)

            dragon_hp_before = dragon.hp
            enemy_damage = 0
            dragon_hp_after = dragon_hp_before
            if enemy_hp_after > 0:
                enemy_damage = roll_enemy_damage(enemy, rng=rng)
                dragon_hp_after = dragon_hp_before - enemy_damage

            lost = enemy_hp_after > 0 and dragon_hp_after <= BATTLE_DRAGON_MIN_HP
            if lost:
                # The dragon is only weakened; it is never removed.
                dragon_hp_after = BATTLE_DRAGON_MIN_HP
            dragon_hp_after = max(BATTLE_DRAGON_MIN_HP, min(dragon.max_hp, dragon_hp_after))
            won = enemy_hp_after <= 0

            result = AttackResult(
                success=True,
                battle=battle,
                enemy=enemy,
                dragon=dragon,
                dragon_damage=dragon_damage,
                enemy_damage=enemy_damage,
                enemy_hp_before=enemy_hp_before,
                enemy_hp_after=enemy_hp_after,
                dragon_hp_before=dragon_hp_before,
                dragon_hp_after=dragon_hp_after,
                won=won,
                lost=lost,
            )

            rewards: dict[str, int] = {}
            xp_gain = 0
            with get_db() as conn:
                if won or lost:
                    if won:
                        rewards = self.roll_rewards(enemy, rng=rng)
                        xp_gain = rewards.pop("xp", 0)
                        snapshot = dict(rewards)
                        snapshot["xp"] = xp_gain
                        self.players.add_resources(
                            user_id,
                            obsidian=rewards.get("obsidian", 0),
                            aether=rewards.get("aether", 0),
                            conn=conn,
                        )
                    else:
                        snapshot = {}
                    status = STATUS_WON if won else STATUS_LOST
                    # Guarded close: a second simultaneous press changes nothing.
                    if not self.battles.finish(
                        battle_id,
                        status,
                        now,
                        enemy_hp=enemy_hp_after,
                        reward=snapshot or None,
                        conn=conn,
                    ):
                        return AttackResult(
                            success=False, reason="finished", battle=battle
                        )
                else:
                    if not self.battles.apply_turn(
                        battle_id, enemy_hp_after, now, battle.turns, conn=conn
                    ):
                        # Someone else's press already applied this turn.
                        return AttackResult(
                            success=False, reason="finished", battle=battle
                        )
                self.dragons.set_hp(dragon.id, dragon_hp_after, conn=conn)

            # XP goes through the normal system so level-ups work as usual.
            if xp_gain > 0:
                xp_result = self.dragon_service.add_xp(dragon.id, xp_gain)
                if xp_result is not None:
                    result.xp_gained = xp_result.xp_added
                    result.level_ups = list(xp_result.level_ups)
                    result.dragon = xp_result.dragon

            if result.dragon is None or result.dragon.id != dragon.id:
                result.dragon = dragon
            refreshed = self.dragons.get(dragon.id)
            if refreshed is not None:
                result.dragon = refreshed
                result.dragon_hp_after = refreshed.hp
            result.rewards = rewards
            result.battle = self.battles.get(battle_id) or battle
            result.enemy = get_enemy(battle.enemy_id, enemy_hp_after)
            return result
        except Exception:
            logger.exception("attack failed for battle %s / user %s", battle_id, user_id)
            return AttackResult(success=False, reason="error")

    # --- fleeing -----------------------------------------------------------
    def flee(
        self, battle_id: int, user_id: int, now: Optional[float] = None
    ) -> FleeResult:
        """End a battle with no rewards and no saved progress."""
        now = now if now is not None else time.time()
        try:
            battle = self.battles.get(battle_id)
            if battle is None:
                return FleeResult(success=False, reason="not_found")
            if battle.user_id != user_id:
                return FleeResult(success=False, reason="not_owner", battle=battle)
            if not battle.is_active:
                return FleeResult(success=False, reason="finished", battle=battle)
            if not self.battles.finish(battle_id, STATUS_FLED, now):
                return FleeResult(success=False, reason="finished", battle=battle)
            return FleeResult(
                success=True,
                battle=self.battles.get(battle_id) or battle,
                enemy=get_enemy(battle.enemy_id, battle.enemy_hp),
                dragon=self.dragons.get(battle.dragon_id),
            )
        except Exception:
            logger.exception("flee failed for battle %s / user %s", battle_id, user_id)
            return FleeResult(success=False, reason="error")

    # --- rewards -----------------------------------------------------------
    def roll_rewards(self, enemy: Enemy, rng: Optional[random.Random] = None) -> dict:
        """Roll the victory rewards: obsidian + XP, with a rare aether bonus."""
        rng = rng or random
        rewards = {
            "obsidian": rng.randint(enemy.reward_min, enemy.reward_max),
            "xp": rng.randint(enemy.xp_min, enemy.xp_max),
        }
        if rng.random() < BATTLE_AETHER_CHANCE:
            rewards["aether"] = rng.randint(BATTLE_AETHER_MIN, BATTLE_AETHER_MAX)
        return rewards

    # --- maintenance -------------------------------------------------------
    def expire_stale_battles(self, now: Optional[float] = None) -> list[Battle]:
        """Abandon battles nobody touched within ``BATTLE_STALE_SECONDS``."""
        now = now if now is not None else time.time()
        try:
            return self.battles.expire_older_than(now - BATTLE_STALE_SECONDS)
        except Exception:
            logger.exception("expire_stale_battles failed")
            return []

    def active_battle(self, user_id: int) -> Optional[Battle]:
        return self.battles.get_active_for_user(user_id)
