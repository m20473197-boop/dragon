"""Market rules (no Telegram code here).

Players spend 🪨 obsidian to buy:

* 🥩 meat / 🐟 fish — deposited straight into the cold storage,
* 🥚 a common dragon egg — created through the **existing** egg system
  (``EggService.create_found_egg``), so it incubates and hatches exactly like
  an egg found while gathering. No new egg mechanics are introduced.

Every purchase runs in one transaction and pays with a guarded UPDATE
(``spend_currency``), so a balance can never go negative and a double tap can
never buy twice with the same coins. There is no selling, and aether is never
spent (it stays a store-only currency).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from config import MARKET_CATEGORIES, MARKET_ITEMS
from database.connection import get_db
from game.eggs import EggService
from game.storage import ColdStorageService
from models.player import PlayerRepository

logger = logging.getLogger(__name__)

# The market only ever charges in obsidian.
CURRENCY_COLUMN = "obsidian"


@dataclass
class PurchaseResult:
    """Outcome of one purchase attempt."""

    success: bool
    reason: str = ""              # "unknown_item" | "not_enough" | "failed"
    category: Optional[str] = None
    item_key: Optional[str] = None
    item: Optional[dict] = None   # the config entry that was bought
    price: int = 0
    amount: int = 0               # how many units were granted
    balance: int = 0              # obsidian remaining after the purchase
    missing: int = 0              # obsidian still needed, when rejected
    egg_id: Optional[int] = None  # for egg purchases


def get_item(category: str, item_key: str) -> Optional[dict]:
    """Look up a market item, or None when it does not exist."""
    return MARKET_ITEMS.get(category, {}).get(item_key)


def list_category(category: str) -> dict:
    """All items in a category ({} for an empty/unknown category)."""
    return MARKET_ITEMS.get(category, {})


def category_display(category: str) -> tuple[str, str]:
    """Return (emoji, persian_name) for a market category."""
    info = MARKET_CATEGORIES[category]
    return info["emoji"], info["name"]


class MarketService:
    def __init__(
        self,
        players: Optional[PlayerRepository] = None,
        storage: Optional[ColdStorageService] = None,
        egg_service: Optional[EggService] = None,
    ) -> None:
        self.players = players or PlayerRepository()
        self.storage = storage or ColdStorageService(self.players)
        self.egg_service = egg_service or EggService(players=self.players)

    # --- reading -----------------------------------------------------------
    def balance(self, user_id: int) -> int:
        """The player's obsidian balance (0 for an unknown player)."""
        player = self.players.get(user_id)
        return player.obsidian if player else 0

    def can_afford(self, user_id: int, category: str, item_key: str) -> bool:
        item = get_item(category, item_key)
        if item is None:
            return False
        return self.balance(user_id) >= item["price"]

    # --- buying ------------------------------------------------------------
    def buy(
        self,
        user_id: int,
        category: str,
        item_key: str,
        chat_id: Optional[int] = None,
    ) -> PurchaseResult:
        """Buy one market item for ``user_id``, paying in obsidian.

        ``chat_id`` is recorded on a purchased egg (the group the purchase was
        made in) so it behaves like any other egg owned by the player.
        """
        item = get_item(category, item_key)
        if item is None:
            return PurchaseResult(success=False, reason="unknown_item")

        price = int(item["price"])

        # Cheap pre-check so we can report exactly how much is missing; the
        # authoritative check is the guarded spend below.
        balance = self.balance(user_id)
        if balance < price:
            return PurchaseResult(
                success=False, reason="not_enough", category=category,
                item_key=item_key, item=item, price=price,
                balance=balance, missing=price - balance,
            )

        if item["kind"] == "food":
            return self._buy_food(user_id, category, item_key, item, price)
        if item["kind"] == "egg":
            return self._buy_egg(user_id, category, item_key, item, price, chat_id)
        return PurchaseResult(success=False, reason="unknown_item")

    def _buy_food(self, user_id, category, item_key, item, price) -> PurchaseResult:
        amount = int(item["amount"])
        with get_db() as conn:
            # Guarded spend: fails (changing nothing) if the balance is short.
            if not self.players.spend_currency(
                user_id, CURRENCY_COLUMN, price, conn=conn
            ):
                balance = self.balance(user_id)
                return PurchaseResult(
                    success=False, reason="not_enough", category=category,
                    item_key=item_key, item=item, price=price,
                    balance=balance, missing=max(0, price - balance),
                )
            # Food always goes into the cold storage.
            self.storage.deposit(
                user_id, **{item["resource"]: amount}, conn=conn
            )
            player = self.players.get(user_id, conn=conn)

        return PurchaseResult(
            success=True, category=category, item_key=item_key, item=item,
            price=price, amount=amount, balance=player.obsidian if player else 0,
        )

    def _buy_egg(self, user_id, category, item_key, item, price, chat_id) -> PurchaseResult:
        # Pay first (guarded); only then create the egg.
        if not self.players.spend_currency(user_id, CURRENCY_COLUMN, price):
            balance = self.balance(user_id)
            return PurchaseResult(
                success=False, reason="not_enough", category=category,
                item_key=item_key, item=item, price=price,
                balance=balance, missing=max(0, price - balance),
            )

        try:
            # Reuse the existing egg pipeline: an owned, incubating egg that
            # hatches on the normal schedule (no new mechanics).
            egg = self.egg_service.create_found_egg(
                chat_id if chat_id is not None else user_id,
                user_id,
                egg_type=item.get("egg_type"),
            )
        except Exception:
            # Never charge for an egg the player did not get.
            logger.exception("Market: egg creation failed; refunding %s", user_id)
            self.players.add_resources(user_id, obsidian=price)
            return PurchaseResult(
                success=False, reason="failed", category=category,
                item_key=item_key, item=item, price=price,
                balance=self.balance(user_id),
            )

        return PurchaseResult(
            success=True, category=category, item_key=item_key, item=item,
            price=price, amount=1, balance=self.balance(user_id), egg_id=egg.id,
        )
