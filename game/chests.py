"""Random chest logic and reward rolling (no Telegram code here).

A chest can appear in an active group. The first user to press the button wins
it: the open is a single conditional UPDATE, so exactly one user can ever open
a given chest. Rewards are rolled from ``config.CHEST_REWARDS``:

* 🪨 obsidian — always granted (the main currency),
* ✨ aether  — rare, rolled with a much lower chance,
* 🥩 meat / 🐟 fish — go straight into the player's cold storage.

Currency and food are credited in a single transaction together with the
chest's reward snapshot, so a reward can never be granted twice or lost.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from config import CHEST_OPEN_WINDOW_SECONDS, CHEST_REWARDS, CURRENCIES
from database.connection import get_db
from game.storage import ColdStorageService
from models.chest import Chest, ChestRepository
from models.player import PlayerRepository

logger = logging.getLogger(__name__)

# Which reward keys are currencies vs. cold-storage food.
CURRENCY_KEYS = tuple(CURRENCIES)
FOOD_KEYS = ("meat", "fish")


@dataclass
class ChestOpenResult:
    """Outcome of a chest open attempt."""

    success: bool
    reason: str = ""                 # "not_found" | "already_opened" | "expired"
    chest: Optional[Chest] = None
    rewards: dict = field(default_factory=dict)  # {"obsidian": 850, "meat": 15, ...}
    opened_by: Optional[int] = None

    @property
    def obsidian(self) -> int:
        return self.rewards.get("obsidian", 0)

    @property
    def aether(self) -> int:
        return self.rewards.get("aether", 0)


def roll_rewards(rng: Optional[random.Random] = None) -> dict:
    """Roll a random reward set from the configured table.

    Obsidian is always included (chance 1.0); the rest are rolled
    independently, so aether stays rare. Keys with a zero roll are omitted.
    """
    rng = rng or random
    rewards: dict[str, int] = {}
    for key, spec in CHEST_REWARDS.items():
        if rng.random() >= spec["chance"]:
            continue
        amount = rng.randint(spec["min"], spec["max"])
        if amount > 0:
            rewards[key] = amount
    # Safety net: a chest always gives at least some obsidian.
    if "obsidian" not in rewards:
        spec = CHEST_REWARDS["obsidian"]
        rewards["obsidian"] = rng.randint(spec["min"], spec["max"])
    return rewards


class ChestService:
    def __init__(
        self,
        chests: Optional[ChestRepository] = None,
        players: Optional[PlayerRepository] = None,
        storage: Optional[ColdStorageService] = None,
    ) -> None:
        self.chests = chests or ChestRepository()
        self.players = players or PlayerRepository()
        self.storage = storage or ColdStorageService(self.players)

    # --- spawning ----------------------------------------------------------
    def spawn_chest(
        self, group_id: int, now: Optional[float] = None, is_test: int = 0,
        force: bool = False,
    ) -> Optional[Chest]:
        """Spawn a chest in a group (skipped if one is already waiting)."""
        now = now if now is not None else time.time()
        return self.chests.spawn_if_group_free(
            group_id, created_time=now, is_test=is_test, force=force
        )

    # --- opening -----------------------------------------------------------
    def open_chest(
        self, chest_id: int, user_id: int, now: Optional[float] = None,
        rng: Optional[random.Random] = None,
    ) -> ChestOpenResult:
        """Open a chest for ``user_id`` and grant the rolled rewards.

        Only the first caller wins; everyone else gets ``already_opened``.
        """
        now = now if now is not None else time.time()

        chest = self.chests.get(chest_id)
        if chest is None:
            return ChestOpenResult(success=False, reason="not_found")
        if chest.status != "available":
            return ChestOpenResult(
                success=False,
                reason="already_opened" if chest.opened_by else "expired",
                chest=chest,
                opened_by=chest.opened_by,
            )

        with get_db() as conn:
            # Atomic winner selection: exactly one caller can flip the row.
            if not self.chests.claim_for_opening(chest_id, user_id, now, conn=conn):
                current = self.chests.get(chest_id, conn=conn)
                return ChestOpenResult(
                    success=False,
                    reason="already_opened" if (current and current.opened_by) else "expired",
                    chest=current,
                    opened_by=current.opened_by if current else None,
                )

            rewards = roll_rewards(rng)
            # Make sure the opener exists before crediting them.
            self.players.get_or_create(user_id, None, conn=conn)

            # Currencies straight onto the player row; food into cold storage
            # (same columns, but routed through the storage service so the
            # cold storage stays the single owner of meat/fish).
            self.players.add_resources(
                user_id,
                obsidian=rewards.get("obsidian", 0),
                aether=rewards.get("aether", 0),
                conn=conn,
            )
            self.storage.deposit(
                user_id,
                meat=rewards.get("meat", 0),
                fish=rewards.get("fish", 0),
                conn=conn,
            )
            self.chests.set_reward(chest_id, rewards, conn=conn)
            opened = self.chests.get(chest_id, conn=conn)

        return ChestOpenResult(
            success=True, chest=opened, rewards=rewards, opened_by=user_id
        )

    # --- maintenance -------------------------------------------------------
    def expire_stale_chests(self, now: Optional[float] = None) -> list[Chest]:
        """Expire chests nobody opened within the open window."""
        now = now if now is not None else time.time()
        return self.chests.expire_older_than(now - CHEST_OPEN_WINDOW_SECONDS)

    # --- reading -----------------------------------------------------------
    def balances(self, user_id: int) -> tuple[int, int]:
        """The player's (obsidian, aether)."""
        player = self.players.get(user_id)
        if player is None:
            return 0, 0
        return player.obsidian, player.aether


def currency_display(key: str) -> tuple[str, str]:
    """Return (emoji, persian_name) for a currency key."""
    info = CURRENCIES[key]
    return info["emoji"], info["name"]
