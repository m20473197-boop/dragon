"""Dragon Treasury (خزانه): a read-only view of what a player owns.

This module owns NO storage of its own. It is a pure aggregation layer that
reads the values the existing systems already maintain:

* currencies  -> ``players.obsidian`` / ``players.aether``
* food        -> :class:`game.storage.ColdStorageService` (the single owner of
  meat/fish), never the player row directly
* eggs        -> the ``eggs`` table, grouped by type
* tools       -> ``players.rod_level`` / ``players.weapon_level`` (V6)

Nothing here writes to the database, so the treasury can never desync from —
or duplicate — the cold storage, market or chest systems.

No Telegram imports: this is game logic only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from config import CURRENCIES, EGG_TYPES, TOOL_MIN_LEVEL
from game.storage import ColdStorageService
from game.tools import ROD, WEAPON, clamp_level, tool_display
from models.egg import EggRepository
from models.player import PlayerRepository


@dataclass
class EggStack:
    """A single egg type and how many of them the player is incubating."""

    key: str
    emoji: str
    name: str
    count: int


@dataclass
class TreasuryContents:
    """Everything the treasury screen needs, already resolved to plain ints."""

    obsidian: int = 0
    aether: int = 0
    meat: int = 0
    fish: int = 0
    eggs: list[EggStack] = field(default_factory=list)
    rod_level: int = TOOL_MIN_LEVEL
    weapon_level: int = TOOL_MIN_LEVEL

    @property
    def rod_name(self) -> str:
        return tool_display(ROD, self.rod_level)[1]

    @property
    def weapon_name(self) -> str:
        return tool_display(WEAPON, self.weapon_level)[1]

    @property
    def total_eggs(self) -> int:
        return sum(stack.count for stack in self.eggs)


def egg_short_name(egg_type: str) -> str:
    """Compact label for an egg type («تخم معمولی»), for tight UI lines."""
    spec = EGG_TYPES.get(egg_type, {})
    return spec.get("short") or spec.get("name", egg_type)


class TreasuryService:
    """Reads the player's holdings from the existing systems."""

    def __init__(
        self,
        players: Optional[PlayerRepository] = None,
        eggs: Optional[EggRepository] = None,
        storage: Optional[ColdStorageService] = None,
    ) -> None:
        self.players = players or PlayerRepository()
        self.eggs = eggs or EggRepository()
        # Reuse the cold storage service so meat/fish have exactly one owner.
        self.storage = storage or ColdStorageService(self.players)

    def contents(self, user_id: int) -> TreasuryContents:
        """The player's currencies, food and eggs.

        A player with nothing (or one that does not exist yet) yields zeros
        rather than an error, so the screen always renders.
        """
        player = self.players.get(user_id)
        food = self.storage.contents(user_id)
        counts = self.eggs.count_incubating_by_type(user_id)

        # Every configured egg type is listed, so a missing type shows 0
        # instead of vanishing from the screen.
        stacks = [
            EggStack(
                key=key,
                emoji=spec["emoji"],
                name=egg_short_name(key),
                count=counts.get(key, 0),
            )
            for key, spec in EGG_TYPES.items()
        ]

        return TreasuryContents(
            obsidian=player.obsidian if player else 0,
            aether=player.aether if player else 0,
            meat=food.meat,
            fish=food.fish,
            eggs=stacks,
            rod_level=clamp_level(player.rod_level) if player else TOOL_MIN_LEVEL,
            weapon_level=(
                clamp_level(player.weapon_level) if player else TOOL_MIN_LEVEL
            ),
        )

    def currency_emoji(self, key: str) -> str:
        return CURRENCIES[key]["emoji"]
