"""Egg lifecycle rules (no Telegram code here).

Covers spawning, claiming, personal finds, automatic hatching and expiry.
Telegram-facing code lives in ``handlers/``; this module only manipulates the
database through repositories and returns plain objects describing what
happened.

Every operation that writes to more than one table (or must be race-safe) runs
inside a single transaction via ``with get_db() as conn``, so a failure mid-way
rolls back and concurrent requests can't create duplicate effects.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from config import (
    CLAIM_WINDOW_SECONDS,
    DRAGON_TYPES,
    EGG_TYPES,
)
from database.connection import get_db
from game import hatch_override
from game.dragons import DragonService
from models.dragon import Dragon, DragonRepository
from models.egg import (
    Egg,
    EggRepository,
    STATUS_EXPIRED,
    STATUS_INCUBATING,
)
from models.player import PlayerRepository
from utils.rng import weighted_choice


@dataclass
class HatchEvent:
    """Everything the notification layer needs to announce a hatching."""

    egg: Egg
    dragon: Dragon
    owner_id: int
    chat_id: int


class EggService:
    def __init__(
        self,
        eggs: Optional[EggRepository] = None,
        dragons: Optional[DragonRepository] = None,
        players: Optional[PlayerRepository] = None,
        dragon_service: Optional[DragonService] = None,
    ) -> None:
        self.eggs = eggs or EggRepository()
        self.dragons = dragons or DragonRepository()
        self.players = players or PlayerRepository()
        # The dragon service creates newborn dragons; it reuses the same
        # repository so the service and repository stay in sync.
        self.dragon_service = dragon_service or DragonService(dragons=self.dragons)

    # --- randomness --------------------------------------------------------
    @staticmethod
    def random_egg_type() -> str:
        return weighted_choice({k: v["weight"] for k, v in EGG_TYPES.items()})

    @staticmethod
    def random_dragon_type(egg_type: str) -> str:
        return weighted_choice(EGG_TYPES[egg_type]["dragons"])

    @staticmethod
    def hatch_seconds(egg_type: str) -> int:
        """Production hatch time, unless the admin debug override is active."""
        return hatch_override.get_hatch_seconds(EGG_TYPES[egg_type]["hatch_seconds"])

    # --- spawning / claiming ----------------------------------------------
    def spawn_wild_egg(self, chat_id: int, now: Optional[float] = None) -> Optional[Egg]:
        """Spawn an unclaimed egg in a group.

        Returns None if an unclaimed egg is already waiting in that group.
        Atomic: the check and insert are one statement.
        """
        now = now if now is not None else time.time()
        egg_type = self.random_egg_type()
        return self.eggs.spawn_if_chat_free(egg_type, chat_id, now)

    def create_found_egg(
        self, chat_id: int, owner_id: int, now: Optional[float] = None
    ) -> Egg:
        """An egg found while gathering: immediately owned and incubating."""
        now = now if now is not None else time.time()
        egg_type = self.random_egg_type()
        hatch_seconds = self.hatch_seconds(egg_type)
        with get_db() as conn:
            egg = self.eggs.create(
                egg_type=egg_type,
                chat_id=chat_id,
                spawn_time=now,
                owner_id=owner_id,
                status=STATUS_INCUBATING,
                claim_time=now,
                hatch_time=now + hatch_seconds,
                conn=conn,
            )
            # Keep the denormalized counter in sync in the same transaction.
            self.players.add_resources(owner_id, eggs=1, conn=conn)
        return egg

    def claim_egg(
        self, egg_id: int, user_id: int, now: Optional[float] = None
    ) -> tuple[Optional[Egg], Optional[Egg]]:
        """Try to claim an egg. Returns ``(claimed_egg, current_egg)``.

        * If this user won the race: ``(egg, egg)`` (status incubating).
        * If someone else got it first (or it expired): ``(None, egg)``.
        * If the egg no longer exists: ``(None, None)``.
        """
        now = now if now is not None else time.time()
        with get_db() as conn:
            egg = self.eggs.get(egg_id, conn=conn)
            if egg is None:
                return None, None

            won = self.eggs.claim(
                egg_id=egg_id,
                user_id=user_id,
                claim_time=now,
                hatch_time=now + self.hatch_seconds(egg.egg_type),
                claim_window_seconds=CLAIM_WINDOW_SECONDS,
                conn=conn,
            )
            if won:
                self.players.add_resources(user_id, eggs=1, conn=conn)
            current = self.eggs.get(egg_id, conn=conn)

        return (current, current) if won else (None, current)

    # --- hatching / expiry -------------------------------------------------
    def process_hatchings(self, now: Optional[float] = None) -> list[HatchEvent]:
        """Hatch every incubating egg whose time is up. Returns the events.

        Each egg is hatched in its own transaction and the status flip is
        guarded, so a dragon can never be created twice for the same egg.
        """
        now = now if now is not None else time.time()
        events: list[HatchEvent] = []

        for egg in self.eggs.find_due_hatch(now):
            if egg.owner_id is None:  # defensive; should not happen
                with get_db() as conn:
                    self.eggs.mark_status(egg.id, STATUS_EXPIRED, conn=conn)
                continue

            dragon_type = self.random_dragon_type(egg.egg_type)
            with get_db() as conn:
                # Idempotent guard: only the first transition succeeds.
                if not self.eggs.transition_to_hatched(egg.id, now, conn=conn):
                    continue
                # Create the newborn dragon (level 1, default stats).
                dragon = self.dragon_service.create_newborn(
                    owner_id=egg.owner_id,
                    dragon_type=dragon_type,
                    from_egg_id=egg.id,
                    conn=conn,
                )
                # Egg became a dragon: eggs counter down, dragons counter up.
                self.players.add_resources(egg.owner_id, eggs=-1, dragons=1, conn=conn)
                # First dragon becomes the owner's active dragon automatically.
                if self.players.get_active_dragon_id(egg.owner_id, conn=conn) is None:
                    self.players.set_active_dragon(egg.owner_id, dragon.id, conn=conn)
                fresh_egg = self.eggs.get(egg.id, conn=conn)

            events.append(
                HatchEvent(
                    egg=fresh_egg,
                    dragon=dragon,
                    owner_id=egg.owner_id,
                    chat_id=egg.chat_id,
                )
            )
        return events

    def expire_stale_eggs(self, now: Optional[float] = None) -> list[Egg]:
        """Mark unclaimed eggs that passed the claim window as expired.

        Returns the eggs with their (updated) expired status.
        """
        now = now if now is not None else time.time()
        stale = self.eggs.find_stale_available(CLAIM_WINDOW_SECONDS, now)
        expired: list[Egg] = []
        for egg in stale:
            with get_db() as conn:
                self.eggs.mark_status(egg.id, STATUS_EXPIRED, conn=conn)
                fresh = self.eggs.get(egg.id, conn=conn)
            expired.append(fresh)
        return expired


def dragon_display(dragon_type: str) -> tuple[str, str]:
    """Return (emoji, persian_name) for a dragon type."""
    info = DRAGON_TYPES[dragon_type]
    return info["emoji"], info["name"]


def egg_display(egg_type: str) -> tuple[str, str]:
    """Return (emoji, persian_name) for an egg type."""
    info = EGG_TYPES[egg_type]
    return info["emoji"], info["name"]
