"""Breeding ritual model and repository (Version 9).

Owns all SQL for the ``breedings`` table. One row is one 🧬 آیین پیوند: the
two parents, when it finishes, what it cost and (once done) the child it
produced. The busy flag on the parents themselves lives on the ``dragons``
table (see :meth:`models.dragon.DragonRepository.mark_breeding`).

No game rules here — the pairing, cost and outcome maths belong to
:mod:`game.breeding`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from database.connection import db_scope

STATUS_ACTIVE = "active"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"


@dataclass
class Breeding:
    breeding_id: int
    owner_id: int
    parent1_id: int
    parent2_id: int
    status: str = STATUS_ACTIVE
    start_time: float = 0.0
    finish_time: float = 0.0
    chat_id: Optional[int] = None
    cost: int = 0
    child_id: Optional[int] = None
    outcome: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Breeding":
        keys = row.keys()
        return cls(
            breeding_id=row["breeding_id"],
            owner_id=row["owner_id"],
            parent1_id=row["parent1_id"],
            parent2_id=row["parent2_id"],
            status=row["status"],
            start_time=row["start_time"],
            finish_time=row["finish_time"],
            chat_id=row["chat_id"] if "chat_id" in keys else None,
            cost=row["cost"] if "cost" in keys else 0,
            child_id=row["child_id"] if "child_id" in keys else None,
            outcome=row["outcome"] if "outcome" in keys else None,
        )

    @property
    def parents(self) -> tuple[int, int]:
        return (self.parent1_id, self.parent2_id)

    def remaining(self, now: Optional[float] = None) -> int:
        """Whole seconds left, never negative."""
        now = now if now is not None else time.time()
        return max(0, int(round(self.finish_time - now)))


class BreedingRepository:
    """CRUD for breeding rituals."""

    def create(
        self,
        owner_id: int,
        parent1_id: int,
        parent2_id: int,
        start_time: float,
        finish_time: float,
        cost: int,
        chat_id: Optional[int] = None,
        conn=None,
    ) -> Breeding:
        with db_scope(conn) as c:
            cur = c.execute(
                "INSERT INTO breedings (owner_id, parent1_id, parent2_id, "
                "status, start_time, finish_time, chat_id, cost) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (owner_id, parent1_id, parent2_id, STATUS_ACTIVE, start_time,
                 finish_time, chat_id, cost),
            )
            breeding_id = int(cur.lastrowid)
        return Breeding(
            breeding_id=breeding_id,
            owner_id=owner_id,
            parent1_id=parent1_id,
            parent2_id=parent2_id,
            status=STATUS_ACTIVE,
            start_time=start_time,
            finish_time=finish_time,
            chat_id=chat_id,
            cost=cost,
        )

    def get(self, breeding_id: int, conn=None) -> Optional[Breeding]:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM breedings WHERE breeding_id = ?", (breeding_id,)
            ).fetchone()
        return None if row is None else Breeding.from_row(row)

    def active_for_owner(self, owner_id: int, conn=None) -> Optional[Breeding]:
        """The owner's in-progress ritual, if any (at most one is expected)."""
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM breedings WHERE owner_id = ? AND status = ? "
                "ORDER BY breeding_id DESC LIMIT 1",
                (owner_id, STATUS_ACTIVE),
            ).fetchone()
        return None if row is None else Breeding.from_row(row)

    def find_due(self, now: Optional[float] = None, conn=None) -> list[Breeding]:
        """Active rituals whose timer has elapsed."""
        now = now if now is not None else time.time()
        with db_scope(conn) as c:
            rows = c.execute(
                "SELECT * FROM breedings WHERE status = ? AND finish_time <= ? "
                "ORDER BY finish_time",
                (STATUS_ACTIVE, now),
            ).fetchall()
        return [Breeding.from_row(r) for r in rows]

    def complete(
        self,
        breeding_id: int,
        child_id: int,
        outcome: str,
        conn=None,
    ) -> bool:
        """Mark a ritual finished. Guarded so it can only happen once."""
        with db_scope(conn) as c:
            cur = c.execute(
                "UPDATE breedings SET status = ?, child_id = ?, outcome = ? "
                "WHERE breeding_id = ? AND status = ?",
                (STATUS_DONE, child_id, outcome, breeding_id, STATUS_ACTIVE),
            )
            return cur.rowcount == 1

    def cancel(self, breeding_id: int, conn=None) -> bool:
        with db_scope(conn) as c:
            cur = c.execute(
                "UPDATE breedings SET status = ? WHERE breeding_id = ? "
                "AND status = ?",
                (STATUS_CANCELLED, breeding_id, STATUS_ACTIVE),
            )
            return cur.rowcount == 1

    def count_by_owner(self, owner_id: int, conn=None) -> int:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM breedings WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
        return int(row["n"]) if row is not None else 0
