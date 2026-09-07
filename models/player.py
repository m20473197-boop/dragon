"""Player model and PlayerRepository.

The Player dataclass is the in-memory representation of a player; the
PlayerRepository owns *all* SQL for the ``players`` table so the rest of
the code never writes raw queries.

Write methods accept an optional ``conn`` so a service can run several writes
inside one transaction (see database.connection.db_scope).
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Optional

from database.connection import db_scope, get_db

logger = logging.getLogger(__name__)

# Cooldown column -> the time the player must wait between uses.
_COOLDOWN_COLUMNS = {"last_hunt_time", "last_fishing_time"}


@dataclass
class Player:
    user_id: int
    username: Optional[str] = None
    meat: int = 0
    fish: int = 0
    eggs: int = 0
    dragons: int = 0
    last_hunt_time: Optional[float] = None
    last_fishing_time: Optional[float] = None

    @classmethod
    def from_row(cls, row) -> "Player":
        return cls(
            user_id=row["user_id"],
            username=row["username"],
            meat=row["meat"],
            fish=row["fish"],
            eggs=row["eggs"],
            dragons=row["dragons"],
            last_hunt_time=row["last_hunt_time"],
            last_fishing_time=row["last_fishing_time"],
        )


class PlayerRepository:
    """CRUD + resource updates for the players table."""

    # --- reads -------------------------------------------------------------
    def get(self, user_id: int, conn=None) -> Optional[Player]:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM players WHERE user_id = ?", (user_id,)
            ).fetchone()
        return Player.from_row(row) if row is not None else None

    # --- writes ------------------------------------------------------------
    def create(self, user_id: int, username: Optional[str], conn=None) -> Player:
        with db_scope(conn) as c:
            c.execute(
                "INSERT INTO players (user_id, username) VALUES (?, ?)",
                (user_id, username),
            )
        logger.info("New player registered: %s (@%s)", user_id, username)
        return Player(user_id=user_id, username=username)

    def get_or_create(
        self, user_id: int, username: Optional[str]
    ) -> tuple[Player, bool]:
        """Return (player, created). Keeps the stored username up to date."""
        with get_db() as conn:
            player = self.get(user_id, conn=conn)
            if player is None:
                return self.create(user_id, username, conn=conn), True
            if player.username != username:
                self.update_username(user_id, username, conn=conn)
                player.username = username
            return player, False

    def update_username(self, user_id: int, username: Optional[str], conn=None) -> None:
        with db_scope(conn) as c:
            c.execute(
                "UPDATE players SET username = ? WHERE user_id = ?",
                (username, user_id),
            )

    def add_resources(
        self,
        user_id: int,
        meat: int = 0,
        fish: int = 0,
        eggs: int = 0,
        dragons: int = 0,
        conn=None,
    ) -> None:
        """Increase resource counters (negative values subtract)."""
        with db_scope(conn) as c:
            c.execute(
                """
                UPDATE players
                   SET meat    = meat + ?,
                       fish    = fish + ?,
                       eggs    = eggs + ?,
                       dragons = dragons + ?
                 WHERE user_id = ?
                """,
                (meat, fish, eggs, dragons, user_id),
            )

    def set_last_action(self, user_id: int, column: str, timestamp: float, conn=None) -> None:
        """Record when a cooldown-based action was last performed."""
        if column not in _COOLDOWN_COLUMNS:
            raise ValueError(f"Unknown cooldown column: {column!r}")
        with db_scope(conn) as c:
            c.execute(
                f"UPDATE players SET {column} = ? WHERE user_id = ?",
                (timestamp, user_id),
            )

    # --- atomic cooldown actions ------------------------------------------
    def try_start_action(
        self,
        user_id: int,
        column: str,
        cooldown_seconds: int,
        now: Optional[float] = None,
        conn=None,
    ) -> Optional[float]:
        """Atomically claim a cooldown slot for an action.

        Performs the check-and-update in a single SQL statement, so even two
        concurrent (e.g. double-clicked) requests cannot both pass the
        cooldown. Returns the timestamp recorded on success, or ``None`` if the
        action is still on cooldown.
        """
        if column not in _COOLDOWN_COLUMNS:
            raise ValueError(f"Unknown cooldown column: {column!r}")
        now = now if now is not None else time.time()
        with db_scope(conn) as c:
            cur = c.execute(
                f"""
                UPDATE players
                   SET {column} = ?
                 WHERE user_id = ?
                   AND ({column} IS NULL OR ? - {column} >= ?)
                """,
                (now, user_id, now, cooldown_seconds),
            )
            return now if cur.rowcount == 1 else None

    def apply_gather(
        self,
        user_id: int,
        column: str,
        cooldown_seconds: int,
        meat: int = 0,
        fish: int = 0,
        now: Optional[float] = None,
        conn=None,
    ) -> Optional[float]:
        """Claim a cooldown slot and grant rewards in ONE atomic transaction.

        Returns the action timestamp on success, or ``None`` if still cooling
        down (in which case nothing is granted). Prevents duplicate rewards
        from rapid/double messages.
        """
        if column not in _COOLDOWN_COLUMNS:
            raise ValueError(f"Unknown cooldown column: {column!r}")
        now = now if now is not None else time.time()
        with db_scope(conn) as c:
            cur = c.execute(
                f"""
                UPDATE players
                   SET {column} = ?,
                       meat = meat + ?,
                       fish = fish + ?
                 WHERE user_id = ?
                   AND ({column} IS NULL OR ? - {column} >= ?)
                """,
                (now, meat, fish, user_id, now, cooldown_seconds),
            )
            if cur.rowcount == 1:
                return now
        return None

    def get_cooldown_remaining(
        self, user_id: int, column: str, cooldown_seconds: int, now: Optional[float] = None
    ) -> int:
        """Whole seconds until the given action is available (0 = ready)."""
        if column not in _COOLDOWN_COLUMNS:
            raise ValueError(f"Unknown cooldown column: {column!r}")
        now = now if now is not None else time.time()
        with get_db() as conn:
            row = conn.execute(
                f"SELECT {column} AS t FROM players WHERE user_id = ?", (user_id,)
            ).fetchone()
        last = row["t"] if row is not None else None
        if last is None:
            return 0
        return max(0, int(math.ceil(cooldown_seconds - (now - last))))
