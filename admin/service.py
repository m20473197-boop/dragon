"""Admin-only operations (no Telegram code here).

Every method is a plain database operation so it can be unit-tested without
Telegram and reused by other interfaces. Handlers in ``admin/handlers.py``
call these after checking permissions.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from config import (
    DRAGON_DEFAULT_HP,
    DRAGON_DEFAULT_LEVEL,
    DRAGON_DEFAULT_MAX_HP,
    DRAGON_DEFAULT_POWER,
    DRAGON_DEFAULT_XP,
    TEST_DRAGON_NAME,
)
from database.connection import get_db
from game import hatch_override
from game.eggs import EggService
from models.chat import ChatRepository
from models.dragon import DragonRepository
from models.egg import EggRepository, Egg
from models.player import PlayerRepository


@dataclass
class UserInfo:
    user_id: int
    username: Optional[str]
    meat: int
    fish: int
    eggs: int
    dragons: int
    hunt_count: int
    fishing_count: int
    dragons_list: list


class AdminService:
    def __init__(
        self,
        players: Optional[PlayerRepository] = None,
        chats: Optional[ChatRepository] = None,
        eggs: Optional[EggRepository] = None,
        dragons: Optional[DragonRepository] = None,
        egg_service: Optional[EggService] = None,
    ) -> None:
        self.players = players or PlayerRepository()
        self.chats = chats or ChatRepository()
        self.eggs = eggs or EggRepository()
        self.dragons = dragons or DragonRepository()
        self.egg_service = egg_service or EggService(
            eggs=self.eggs, dragons=self.dragons, players=self.players
        )

    # --- statistics --------------------------------------------------------
    def game_stats(self) -> dict:
        """Aggregate counters across the whole game."""
        total_hunts, total_fishing = self.players.total_counts()
        return {
            "users": self.players.count_all(),
            "eggs": self.eggs.count_all(),
            "dragons": self.dragons.count_all(),
            "groups": self.chats.count_all(),
            "hunts": total_hunts,
            "fishing": total_fishing,
        }

    # --- user information --------------------------------------------------
    def user_info(self, user_id: int) -> Optional[UserInfo]:
        player = self.players.get(user_id)
        if player is None:
            return None
        return UserInfo(
            user_id=player.user_id,
            username=player.username,
            meat=player.meat,
            fish=player.fish,
            eggs=player.eggs,
            dragons=player.dragons,
            hunt_count=player.hunt_count,
            fishing_count=player.fishing_count,
            dragons_list=self.dragons.list_by_owner(user_id),
        )

    # --- add food to cold storage -----------------------------------------
    def add_food(self, user_id: int, food_key: str, amount: int) -> bool:
        """Add meat/fish to a user's cold storage. Returns True if applied."""
        if food_key not in ("meat", "fish") or amount <= 0:
            return False
        # Ensure the target player exists so food is never lost to a typo.
        player = self.players.get(user_id)
        if player is None:
            return False
        self.players.add_resources(user_id, **{food_key: amount})
        return True

    # --- test egg ----------------------------------------------------------
    def spawn_test_egg(self, chat_id: int, now: Optional[float] = None) -> Optional[Egg]:
        """Spawn a test egg in the current group.

        Uses the same claim/hatch pipeline as a wild egg; only differs by being
        marked ``is_test`` and by ignoring the one-egg-per-group limit and
        honouring the debug hatch-time override.
        """
        now = now if now is not None else time.time()
        egg_type = EggService.random_egg_type()
        with get_db() as conn:
            egg = self.eggs.spawn_if_chat_free(
                egg_type=egg_type,
                chat_id=chat_id,
                spawn_time=now,
                is_test=1,
                force=True,           # test eggs may stack while testing
                conn=conn,
            )
        return egg

    # --- test dragon -------------------------------------------------------
    def create_test_dragon(self, owner_id: int, dragon_type: str = "fire") -> Optional[object]:
        """Create a 'تستی' level-1 dragon directly for a user."""
        with get_db() as conn:
            player = self.players.get(owner_id, conn=conn)
            if player is None:
                return None
            now = time.time()
            dragon = self.dragons.create(
                owner_id=owner_id,
                dragon_type=dragon_type,
                from_egg_id=None,
                name=TEST_DRAGON_NAME,
                level=DRAGON_DEFAULT_LEVEL,
                xp=DRAGON_DEFAULT_XP,
                hp=DRAGON_DEFAULT_HP,
                max_hp=DRAGON_DEFAULT_MAX_HP,
                power=DRAGON_DEFAULT_POWER,
                hunger=100,
                last_fed_time=now,
                is_test=1,
                conn=conn,
            )
            self.players.add_resources(owner_id, dragons=1, conn=conn)
        return dragon

    # --- hatch-time override (testing only) -------------------------------
    def set_hatch_override(self, seconds: Optional[int]) -> None:
        hatch_override.set_hatch_seconds(seconds)

    def hatch_override_seconds(self) -> Optional[int]:
        return hatch_override.current()

    # --- reset test data ---------------------------------------------------
    def reset_test_data(self) -> dict:
        """Delete only admin-created test eggs/dragons.

        Real player rows, resources, and naturally-created dragons/eggs are
        never touched.
        """
        with get_db() as conn:
            eggs_deleted = self.eggs.delete_test(conn=conn)
            dragons_deleted = self.dragons.delete_test(conn=conn)
        return {"eggs": eggs_deleted, "dragons": dragons_deleted}
