"""Core gathering actions (hunting & fishing).

This module contains the *rules* for gathering and no Telegram code, so it can
be tested or reused in another interface. Rewards are rolled first, then the
cooldown is claimed and the resources granted in one atomic SQL update
(``PlayerRepository.apply_gather``), so rapid/double messages can never grant
duplicate rewards. When an action finds an egg it only reports the fact
(``egg_found=True``); the handler layer turns it into a real incubating egg
through ``game.eggs.EggService``.

Reward sizes come from the player's TOOLS (🎣 rod / 🏹 weapon levels, see
``game.tools``): a better tool rolls a bigger range, and a better weapon can
also catch more kinds of prey. Cooldowns, egg chances and XP are unchanged.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Optional

from config import (
    FISHING_COOLDOWN_SECONDS,
    FISHING_EGG_CHANCE,
    HUNT_COOLDOWN_SECONDS,
    HUNT_EGG_CHANCE,
    HUNT_PREY,
)
from game.tools import ROD, WEAPON, allowed_prey, clamp_level, reward_range
from models.player import Player, PlayerRepository
from utils.rng import weighted_choice


@dataclass
class HuntResult:
    """Result of a hunt."""

    success: bool
    cooldown_remaining: int = 0  # set when success is False (still cooling down)
    prey_key: Optional[str] = None  # which animal was caught (key into HUNT_PREY)
    meat_gained: int = 0
    egg_found: bool = False
    action_time: float = 0.0  # timestamp the cooldown was claimed (on success)
    tool_level: int = 1       # 🏹 weapon level used for this hunt


def hunt(repo: PlayerRepository, player: Player) -> HuntResult:
    """🏹 شکار — catch a random animal for meat, with a chance to find an egg.

    The player's 🏹 weapon level decides both which animals can be caught and
    how much meat they yield.
    """
    # Roll the outcome first; nothing is granted until the cooldown is claimed.
    weapon_level = clamp_level(getattr(player, "weapon_level", 1))
    catchable = allowed_prey(weapon_level)
    prey_key = weighted_choice(
        {k: HUNT_PREY[k]["weight"] for k in catchable}
    )
    meat_min, meat_max = reward_range(WEAPON, weapon_level)
    meat_gained = random.randint(meat_min, meat_max)
    egg_found = random.random() < HUNT_EGG_CHANCE

    # The meat goes straight into the player's cold storage (سردخانه). The
    # deposit is folded into the same atomic cooldown update below, so a
    # double-click can neither bypass the cooldown nor double-deposit.
    # (Cold storage meat/fish are the players.meat / players.fish columns; see
    # game.storage.ColdStorageService.)
    now = time.time()
    claimed_at = repo.apply_gather(
        player.user_id,
        column="last_hunt_time",
        cooldown_seconds=HUNT_COOLDOWN_SECONDS,
        meat=meat_gained,
        count_column="hunt_count",
        now=now,
    )
    if claimed_at is None:
        return HuntResult(
            success=False,
            cooldown_remaining=repo.get_cooldown_remaining(
                player.user_id, "last_hunt_time", HUNT_COOLDOWN_SECONDS, now=now
            ),
        )

    # Keep the in-memory player roughly in sync.
    player.meat += meat_gained
    player.last_hunt_time = claimed_at

    return HuntResult(
        success=True,
        prey_key=prey_key,
        meat_gained=meat_gained,
        egg_found=egg_found,
        action_time=claimed_at,
        tool_level=weapon_level,
    )


@dataclass
class FishResult:
    """Result of a fishing trip."""

    success: bool
    cooldown_remaining: int = 0  # set when success is False (still cooling down)
    fish_gained: int = 0
    egg_found: bool = False
    action_time: float = 0.0
    tool_level: int = 1       # 🎣 rod level used for this trip


def fish(repo: PlayerRepository, player: Player) -> FishResult:
    """🎣 ماهیگیری — catch a batch of fish, with a chance to find an egg.

    The player's 🎣 rod level decides how many fish a trip yields.
    """
    rod_level = clamp_level(getattr(player, "rod_level", 1))
    fish_min, fish_max = reward_range(ROD, rod_level)
    fish_gained = random.randint(fish_min, fish_max)
    egg_found = random.random() < FISHING_EGG_CHANCE

    # The fish goes straight into the player's cold storage (سردخانه), folded
    # into the same atomic cooldown update below (players.fish column; see
    # game.storage.ColdStorageService).
    now = time.time()
    claimed_at = repo.apply_gather(
        player.user_id,
        column="last_fishing_time",
        cooldown_seconds=FISHING_COOLDOWN_SECONDS,
        fish=fish_gained,
        count_column="fishing_count",
        now=now,
    )
    if claimed_at is None:
        return FishResult(
            success=False,
            cooldown_remaining=repo.get_cooldown_remaining(
                player.user_id, "last_fishing_time", FISHING_COOLDOWN_SECONDS, now=now
            ),
        )

    player.fish += fish_gained
    player.last_fishing_time = claimed_at

    return FishResult(
        success=True,
        fish_gained=fish_gained,
        egg_found=egg_found,
        action_time=claimed_at,
        tool_level=rod_level,
    )
