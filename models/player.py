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
# Statistics counter columns that may be bumped atomically.
_COUNT_COLUMNS = {"hunt_count", "fishing_count"}
# Currency columns that may be spent (whitelisted: interpolated into SQL).
_CURRENCY_COLUMNS = {"obsidian", "aether"}


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
    hunt_count: int = 0
    fishing_count: int = 0
    active_dragon_id: Optional[int] = None
    obsidian: int = 0
    aether: int = 0

    @classmethod
    def from_row(cls, row) -> "Player":
        keys = row.keys()
        return cls(
            user_id=row["user_id"],
            username=row["username"],
            meat=row["meat"],
            fish=row["fish"],
            eggs=row["eggs"],
            dragons=row["dragons"],
            last_hunt_time=row["last_hunt_time"],
            last_fishing_time=row["last_fishing_time"],
            hunt_count=row["hunt_count"] if "hunt_count" in keys else 0,
            fishing_count=row["fishing_count"] if "fishing_count" in keys else 0,
            active_dragon_id=(
                row["active_dragon_id"] if "active_dragon_id" in keys else None
            ),
            obsidian=row["obsidian"] if "obsidian" in keys else 0,
            aether=row["aether"] if "aether" in keys else 0,
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
        self, user_id: int, username: Optional[str], conn=None
    ) -> tuple[Player, bool]:
        """Return (player, created). Keeps the stored username up to date.

        Accepts an optional ``conn`` so callers can run it inside an existing
        transaction (``db_scope`` reuses the connection instead of opening a
        nested one).
        """
        with db_scope(conn) as c:
            player = self.get(user_id, conn=c)
            if player is None:
                return self.create(user_id, username, conn=c), True
            if username is not None and player.username != username:
                self.update_username(user_id, username, conn=c)
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
        obsidian: int = 0,
        aether: int = 0,
        conn=None,
    ) -> None:
        """Increase resource counters (negative values subtract)."""
        with db_scope(conn) as c:
            c.execute(
                """
                UPDATE players
                   SET meat     = meat + ?,
                       fish     = fish + ?,
                       eggs     = eggs + ?,
                       dragons  = dragons + ?,
                       obsidian = obsidian + ?,
                       aether   = aether + ?
                 WHERE user_id = ?
                """,
                (meat, fish, eggs, dragons, obsidian, aether, user_id),
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

    def spend_resource(self, user_id: int, column: str, amount: int, conn=None) -> bool:
        """Atomically spend ``amount`` of a resource (meat/fish).

        The update only succeeds if the player has enough, so concurrent calls
        cannot spend the same resource twice. Returns True on success.
        """
        if column not in ("meat", "fish"):
            raise ValueError(f"spend_resource only supports meat/fish, got {column!r}")
        if amount < 0:
            raise ValueError("amount must be non-negative")
        with db_scope(conn) as c:
            cur = c.execute(
                f"UPDATE players SET {column} = {column} - ? WHERE user_id = ? AND {column} >= ?",
                (amount, user_id, amount),
            )
            return cur.rowcount == 1

    def spend_currency(self, user_id: int, column: str, amount: int, conn=None) -> bool:
        """Atomically spend ``amount`` of a currency (obsidian/aether).

        The guarded UPDATE only succeeds when the player has enough, so a
        balance can never go negative and two concurrent purchases can never
        spend the same coins twice. Returns True on success.
        """
        if column not in _CURRENCY_COLUMNS:
            raise ValueError(f"Unknown currency column: {column!r}")
        if amount < 0:
            raise ValueError("amount must be non-negative")
        with db_scope(conn) as c:
            cur = c.execute(
                f"UPDATE players SET {column} = {column} - ? "
                f" WHERE user_id = ? AND {column} >= ?",
                (amount, user_id, amount),
            )
            return cur.rowcount == 1

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
        count_column: Optional[str] = None,
        now: Optional[float] = None,
        conn=None,
    ) -> Optional[float]:
        """Claim a cooldown slot and grant rewards in ONE atomic transaction.

        Returns the action timestamp on success, or ``None`` if still cooling
        down (in which case nothing is granted). Prevents duplicate rewards
        from rapid/double messages. ``count_column`` (hunt_count/fishing_count)
        is bumped on success for game statistics.
        """
        if column not in _COOLDOWN_COLUMNS:
            raise ValueError(f"Unknown cooldown column: {column!r}")
        if count_column is not None and count_column not in _COUNT_COLUMNS:
            raise ValueError(f"Unknown count column: {count_column!r}")
        now = now if now is not None else time.time()
        count_sql = f", {count_column} = {count_column} + 1" if count_column else ""
        with db_scope(conn) as c:
            cur = c.execute(
                f"""
                UPDATE players
                   SET {column} = ?,
                       meat = meat + ?,
                       fish = fish + ?
                       {count_sql}
                 WHERE user_id = ?
                   AND ({column} IS NULL OR ? - {column} >= ?)
                """,
                (now, meat, fish, user_id, now, cooldown_seconds),
            )
            if cur.rowcount == 1:
                return now
        return None

    # --- active dragon -----------------------------------------------------
    def set_active_dragon(self, user_id: int, dragon_id: Optional[int], conn=None) -> bool:
        """Mark one dragon as the player's active dragon.

        Only dragons owned by ``user_id`` are accepted (the guarded UPDATE
        checks ownership), which keeps "one active dragon per user" true and
        prevents pointing at somebody else's dragon. Pass ``None`` to clear.
        """
        with db_scope(conn) as c:
            if dragon_id is None:
                cur = c.execute(
                    "UPDATE players SET active_dragon_id = NULL WHERE user_id = ?",
                    (user_id,),
                )
                return cur.rowcount == 1
            cur = c.execute(
                """
                UPDATE players
                   SET active_dragon_id = ?
                 WHERE user_id = ?
                   AND EXISTS (
                        SELECT 1 FROM dragons WHERE id = ? AND owner_id = ?
                   )
                """,
                (dragon_id, user_id, dragon_id, user_id),
            )
            return cur.rowcount == 1

    def get_active_dragon_id(self, user_id: int, conn=None) -> Optional[int]:
        """The player's active dragon id, or None if unset/no longer owned."""
        with db_scope(conn) as c:
            row = c.execute(
                """
                SELECT p.active_dragon_id AS id
                  FROM players p
                  JOIN dragons d
                    ON d.id = p.active_dragon_id AND d.owner_id = p.user_id
                 WHERE p.user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return row["id"] if row is not None else None

    def clear_active_dragon_if(self, user_id: int, dragon_id: int, conn=None) -> None:
        """Unset the active dragon when that dragon disappears."""
        with db_scope(conn) as c:
            c.execute(
                "UPDATE players SET active_dragon_id = NULL "
                " WHERE user_id = ? AND active_dragon_id = ?",
                (user_id, dragon_id),
            )

    def total_currency(self, conn=None) -> tuple[int, int]:
        """Total (obsidian, aether) held by all players — for admin stats."""
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT COALESCE(SUM(obsidian), 0) AS o, COALESCE(SUM(aether), 0) AS a "
                "FROM players"
            ).fetchone()
        return row["o"], row["a"]

    def count_all(self, conn=None) -> int:
        with db_scope(conn) as c:
            row = c.execute("SELECT COUNT(*) AS n FROM players").fetchone()
        return row["n"]

    def total_counts(self, conn=None) -> tuple[int, int]:
        """Total (hunts, fishing trips) across all players."""
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT COALESCE(SUM(hunt_count),0) AS h, COALESCE(SUM(fishing_count),0) AS f FROM players"
            ).fetchone()
        return int(row["h"]), int(row["f"])

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
