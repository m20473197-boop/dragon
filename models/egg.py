"""Egg model and EggRepository.

Owns all SQL for the ``eggs`` table.

Concurrency safety (prevents duplicate actions):

* Claiming is a single conditional ``UPDATE ... WHERE status='available' AND
  owner_id IS NULL`` — even if several users click the button at the same
  instant, exactly one update matches, so exactly one user wins.
* Spawning only inserts when the group has no waiting egg (single statement),
  and hatching only flips an egg that is still ``incubating``, so a crash or
  double sweep can never produce two dragons from one egg.

Write methods accept an optional ``conn`` so a service can compose them inside
one transaction (see database.connection.db_scope).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from database.connection import db_scope

# Egg lifecycle statuses.
STATUS_AVAILABLE = "available"    # spawned, waiting to be claimed
STATUS_INCUBATING = "incubating"  # claimed, waiting to hatch
STATUS_HATCHED = "hatched"
STATUS_EXPIRED = "expired"        # unclaimed past the claim window


@dataclass
class Egg:
    id: int
    egg_type: str
    chat_id: int
    owner_id: Optional[int] = None
    status: str = STATUS_AVAILABLE
    spawn_time: float = 0.0
    claim_time: Optional[float] = None
    hatch_time: Optional[float] = None
    message_id: Optional[int] = None

    @classmethod
    def from_row(cls, row) -> "Egg":
        return cls(
            id=row["id"],
            egg_type=row["egg_type"],
            chat_id=row["chat_id"],
            owner_id=row["owner_id"],
            status=row["status"],
            spawn_time=row["spawn_time"],
            claim_time=row["claim_time"],
            hatch_time=row["hatch_time"],
            message_id=row["message_id"],
        )


class EggRepository:
    def create(
        self,
        egg_type: str,
        chat_id: int,
        spawn_time: float,
        owner_id: Optional[int] = None,
        hatch_time: Optional[float] = None,
        message_id: Optional[int] = None,
        status: str = STATUS_AVAILABLE,
        claim_time: Optional[float] = None,
        conn=None,
    ) -> Egg:
        with db_scope(conn) as c:
            cur = c.execute(
                """
                INSERT INTO eggs
                    (egg_type, chat_id, message_id, owner_id, status,
                     spawn_time, claim_time, hatch_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (egg_type, chat_id, message_id, owner_id, status,
                 spawn_time, claim_time, hatch_time),
            )
            egg_id = cur.lastrowid
        return Egg(
            id=egg_id,
            egg_type=egg_type,
            chat_id=chat_id,
            owner_id=owner_id,
            status=status,
            spawn_time=spawn_time,
            claim_time=claim_time,
            hatch_time=hatch_time,
            message_id=message_id,
        )

    def spawn_if_chat_free(
        self,
        egg_type: str,
        chat_id: int,
        spawn_time: float,
        conn=None,
    ) -> Optional[Egg]:
        """Atomically spawn an available egg only if the group has none.

        Returns the new egg, or ``None`` if an unclaimed egg is already
        waiting in that group (checked and inserted in one statement).
        """
        with db_scope(conn) as c:
            cur = c.execute(
                """
                INSERT INTO eggs (egg_type, chat_id, status, spawn_time)
                SELECT ?, ?, ?, ?
                 WHERE NOT EXISTS (
                     SELECT 1 FROM eggs
                      WHERE chat_id = ? AND status = ?
                 )
                """,
                (egg_type, chat_id, STATUS_AVAILABLE, spawn_time,
                 chat_id, STATUS_AVAILABLE),
            )
            egg_id = cur.lastrowid if cur.rowcount == 1 else None
        if egg_id is None:
            return None
        return self.get(egg_id, conn=conn)

    def get(self, egg_id: int, conn=None) -> Optional[Egg]:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM eggs WHERE id = ?", (egg_id,)
            ).fetchone()
        return Egg.from_row(row) if row is not None else None

    def set_message_id(self, egg_id: int, message_id: int, conn=None) -> None:
        with db_scope(conn) as c:
            c.execute(
                "UPDATE eggs SET message_id = ? WHERE id = ?",
                (message_id, egg_id),
            )

    def count_by_chat_status(self, chat_id: int, status: str, conn=None) -> int:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT COUNT(*) AS c FROM eggs WHERE chat_id = ? AND status = ?",
                (chat_id, status),
            ).fetchone()
        return row["c"]

    def claim(
        self,
        egg_id: int,
        user_id: int,
        claim_time: float,
        hatch_time: float,
        claim_window_seconds: int,
        conn=None,
    ) -> bool:
        """Atomically claim an egg. Returns True only for the winning user.

        The egg must still be ``available``, unowned and within its claim
        window. SQLite serializes writes, so concurrent clicks cannot both win.
        """
        with db_scope(conn) as c:
            cur = c.execute(
                """
                UPDATE eggs
                   SET owner_id   = ?,
                       status     = ?,
                       claim_time = ?,
                       hatch_time = ?
                 WHERE id = ?
                   AND status = ?
                   AND owner_id IS NULL
                   AND spawn_time >= ?
                """,
                (
                    user_id, STATUS_INCUBATING, claim_time, hatch_time,
                    egg_id, STATUS_AVAILABLE,
                    claim_time - claim_window_seconds,
                ),
            )
            return cur.rowcount == 1

    def transition_to_hatched(
        self, egg_id: int, hatch_time_limit: float, conn=None
    ) -> bool:
        """Mark an incubating egg as hatched. Fails if it changed meanwhile.

        Guarding on the current status makes hatching idempotent: a duplicate
        sweep (or two overlapping sweeps) cannot hatch the same egg twice.
        """
        with db_scope(conn) as c:
            cur = c.execute(
                """
                UPDATE eggs
                   SET status = ?
                 WHERE id = ? AND status = ? AND hatch_time IS NOT NULL AND hatch_time <= ?
                """,
                (STATUS_HATCHED, egg_id, STATUS_INCUBATING, hatch_time_limit),
            )
            return cur.rowcount == 1

    def find_due_hatch(self, now: Optional[float] = None, conn=None) -> list[Egg]:
        """Incubating eggs whose hatch_time has passed."""
        now = now if now is not None else time.time()
        with db_scope(conn) as c:
            rows = c.execute(
                """
                SELECT * FROM eggs
                 WHERE status = ? AND hatch_time IS NOT NULL AND hatch_time <= ?
                 ORDER BY hatch_time
                """,
                (STATUS_INCUBATING, now),
            ).fetchall()
        return [Egg.from_row(r) for r in rows]

    def find_stale_available(
        self, claim_window_seconds: int, now: Optional[float] = None, conn=None
    ) -> list[Egg]:
        """Unclaimed eggs whose claim window has expired."""
        now = now if now is not None else time.time()
        with db_scope(conn) as c:
            rows = c.execute(
                """
                SELECT * FROM eggs
                 WHERE status = ? AND spawn_time <= ?
                 ORDER BY spawn_time
                """,
                (STATUS_AVAILABLE, now - claim_window_seconds),
            ).fetchall()
        return [Egg.from_row(r) for r in rows]

    def mark_status(self, egg_id: int, status: str, conn=None) -> None:
        with db_scope(conn) as c:
            c.execute(
                "UPDATE eggs SET status = ? WHERE id = ?", (status, egg_id)
            )

    def list_by_owner(self, owner_id: int, conn=None) -> list[Egg]:
        """All of a user's eggs, newest first."""
        with db_scope(conn) as c:
            rows = c.execute(
                "SELECT * FROM eggs WHERE owner_id = ? ORDER BY id DESC",
                (owner_id,),
            ).fetchall()
        return [Egg.from_row(r) for r in rows]

    def list_active_by_owner(self, owner_id: int, conn=None) -> list[Egg]:
        """The user's currently incubating eggs, soonest hatching first."""
        with db_scope(conn) as c:
            rows = c.execute(
                """
                SELECT * FROM eggs
                 WHERE owner_id = ? AND status = ?
                 ORDER BY hatch_time
                """,
                (owner_id, STATUS_INCUBATING),
            ).fetchall()
        return [Egg.from_row(r) for r in rows]
