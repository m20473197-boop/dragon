"""Cold Storage (سردخانه) — each player's food store.

The cold storage holds the player's 🥩 meat and 🐟 fish. Those amounts already
live per player in the ``players`` table (hunting deposits meat there, fishing
deposits fish there, and feeding consumes them); this service is the named,
single place that *owns* reading and spending those two food resources, so the
rest of the game talks about "the cold storage" rather than raw columns.

It is intentionally basic: no levels, no upgrades and no capacity limits.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models.player import PlayerRepository


@dataclass
class ColdStorageContents:
    meat: int
    fish: int


class ColdStorageService:
    def __init__(self, players: Optional[PlayerRepository] = None) -> None:
        self.players = players or PlayerRepository()

    def contents(self, owner_id: int) -> ColdStorageContents:
        """Current meat/fish stored by the player (0 if unknown player)."""
        player = self.players.get(owner_id)
        if player is None:
            return ColdStorageContents(meat=0, fish=0)
        return ColdStorageContents(meat=player.meat, fish=player.fish)

    def count(self, owner_id: int, food_key: str) -> int:
        """How much of a food type ('meat' / 'fish') the player has stored."""
        if food_key not in ("meat", "fish"):
            raise ValueError(f"Unknown food resource: {food_key!r}")
        return getattr(self.contents(owner_id), food_key)

    def deposit(
        self, owner_id: int, meat: int = 0, fish: int = 0, conn=None
    ) -> None:
        """Add hunted meat / caught fish into cold storage."""
        if meat == 0 and fish == 0:
            return
        self.players.add_resources(owner_id, meat=meat, fish=fish, conn=conn)

    def consume(
        self, owner_id: int, food_key: str, amount: int, conn=None
    ) -> bool:
        """Atomically remove ``amount`` of a food from storage.

        Returns False (and changes nothing) if there is not enough — the
        guarded UPDATE prevents two concurrent feeds from spending the same
        food.
        """
        return self.players.spend_resource(owner_id, food_key, amount, conn=conn)
