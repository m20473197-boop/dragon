"""Market rules (no Telegram code here).

The market sells **tool upgrades only** — 🎣 fishing rods and 🏹 hunting
weapons, priced in 🪨 obsidian and applied by :mod:`game.tools`.

Food and dragon eggs are deliberately **not** purchasable:

* 🥩 meat / 🐟 fish come from 🏹 hunting, 🎣 fishing and 🎁 chests,
* 🥚 dragon eggs come from random spawns and rewards.

Removing them from the shop does not touch the cold storage or the egg system:
players keep everything they already own, and both systems keep working exactly
as before. There is no selling, and aether is never spent (it stays a
store-only currency).
"""
from __future__ import annotations

import logging
from typing import Optional

from config import MARKET_CATEGORIES
from models.player import PlayerRepository

logger = logging.getLogger(__name__)

# The market only ever charges in obsidian.
CURRENCY_COLUMN = "obsidian"


def category_display(category: str) -> tuple[str, str]:
    """Return (emoji, persian_name) for a market category."""
    info = MARKET_CATEGORIES[category]
    return info["emoji"], info["name"]


class MarketService:
    """Reads the balance the market spends; upgrades live in game.tools."""

    def __init__(self, players: Optional[PlayerRepository] = None) -> None:
        self.players = players or PlayerRepository()

    # --- reading -----------------------------------------------------------
    def balance(self, user_id: int) -> int:
        """The player's obsidian balance (0 for an unknown player)."""
        player = self.players.get(user_id)
        return player.obsidian if player else 0
