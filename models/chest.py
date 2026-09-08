"""Chest model and ChestRepository (random mystery chests spawned in groups).

Owns all SQL for the ``chests`` table.

Concurrency safety: opening is a single conditional
``UPDATE ... WHERE status='available' AND opened_by IS NULL``. Even if several
users tap the button at the same instant, exactly one update matches, so a
chest can only ever be opened once by one user.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from database.connection import db_scope

# Chest lifecycle statuses.
STATUS_AVAILABLE = "available"  # spawned, waiting to be opened
STATUS_OPENED = "opened"
STATUS_EXPIRED = "expired"      # nobody opened it within the window


@dataclass
class Chest:
    id: int
    group_id: int
    status: str = STATUS_AVAILABLE
    opened_by: Optional[int] = None
    message_id: Optional[int] = None
    created_time: float = 0.0
    opened_time: Optional[float] = None
    reward: Optional[str] = None
    is_test: int = 0

    @classmethod
    def from_row(cls, row) -> "Chest":
        keys = row.keys()
        return cls(
            id=row["id"],
            group_id=row["group_id"],
            status=row["status"],
            opened_by=row["opened_by"],
            message_id=row["message_id"],
            created_time=row["created_time"],
            opened_time=row["opened_time"],
            reward=row["reward"] if "reward" in keys else None,
            is_test=row["is_test"] if "is_test" in keys else 0,
        )

    def reward_dict(self) -> dict:
        """The stored reward snapshot as a dict ({} when absent/invalid)."""
        if not self.reward:
            return {}
        try:
            return json.loads(self.reward)
        except (ValueError, TypeError):
            return {}


class ChestRepository:
    def create(
        self,
        group_id: int,
        created_time: float,
        message_id: Optional[int] = None,
        is_test: int = 0,
        conn=None,
    ) -> Chest:
        with db_scope(conn) as c:
            cur = c.execute(
                """
                INSERT INTO chests
                    (group_id, message_id, status, is_test, created_time)
                VALUES (?, ?, ?, ?, ?)
                """,
                (group_id, message_id, STATUS_AVAILABLE, is_test, created_time),
            )
            chest_id = cur.lastrowid
        return Chest(
            id=chest_id,
            group_id=group_id,
            message_id=message_id,
            status=STATUS_AVAILABLE,
            is_test=is_test,
            created_time=created_time,
        )

    def spawn_if_group_free(
        self,
        group_id: int,
        created_time: float,
        is_test: int = 0,
        force: bool = False,
        conn=None,
    ) -> Optional[Chest]:
        """Atomically spawn a chest only if the group has no waiting one.

        Returns the new chest, or ``None`` when an unopened chest is already
        present in that group (checked and inserted in one statement).
        ``force=True`` (admin test chests) inserts regardless.
        """
        with db_scope(conn) as c:
            if force:
                cur = c.execute(
                    """
                    INSERT INTO chests (group_id, status, is_test, created_time)
                    VALUES (?, ?, ?, ?)
                    """,
                    (group_id, STATUS_AVAILABLE, is_test, created_time),
                )
            else:
                cur = c.execute(
                    """
                    INSERT INTO chests (group_id, status, is_test, created_time)
                    SELECT ?, ?, ?, ?
                     WHERE NOT EXISTS (
                         SELECT 1 FROM chests
                          WHERE group_id = ? AND status = ?
                     )
                    """,
                    (group_id, STATUS_AVAILABLE, is_test, created_time,
                     group_id, STATUS_AVAILABLE),
                )
            chest_id = cur.lastrowid if cur.rowcount == 1 else None
        if chest_id is None:
            return None
        return Chest(
            id=chest_id,
            group_id=group_id,
            status=STATUS_AVAILABLE,
            is_test=is_test,
            created_time=created_time,
        )

    def get(self, chest_id: int, conn=None) -> Optional[Chest]:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM chests WHERE id = ?", (chest_id,)
            ).fetchone()
        return Chest.from_row(row) if row is not None else None

    def claim_for_opening(self, chest_id: int, user_id: int, now: float, conn=None) -> bool:
        """Atomically mark the chest as opened by ``user_id``.

        Returns True only for the single caller that wins the race; everyone
        else gets False because the row is no longer ``available``.
        """
        with db_scope(conn) as c:
            cur = c.execute(
                """
                UPDATE chests
                   SET status = ?, opened_by = ?, opened_time = ?
                 WHERE id = ? AND status = ? AND opened_by IS NULL
                """,
                (STATUS_OPENED, user_id, now, chest_id, STATUS_AVAILABLE),
            )
            return cur.rowcount == 1

    def set_reward(self, chest_id: int, reward: dict, conn=None) -> None:
        """Persist what the chest granted (JSON snapshot)."""
        with db_scope(conn) as c:
            c.execute(
                "UPDATE chests SET reward = ? WHERE id = ?",
                (json.dumps(reward, ensure_ascii=False), chest_id),
            )

    def set_message_id(self, chest_id: int, message_id: int, conn=None) -> None:
        with db_scope(conn) as c:
            c.execute(
                "UPDATE chests SET message_id = ? WHERE id = ?",
                (message_id, chest_id),
            )

    def expire_older_than(self, cutoff: float, conn=None) -> list[Chest]:
        """Expire unopened chests created before ``cutoff``; returns them."""
        with db_scope(conn) as c:
            rows = c.execute(
                "SELECT * FROM chests WHERE status = ? AND created_time < ?",
                (STATUS_AVAILABLE, cutoff),
            ).fetchall()
            chests = [Chest.from_row(r) for r in rows]
            if chests:
                c.executemany(
                    "UPDATE chests SET status = ? WHERE id = ? AND status = ?",
                    [(STATUS_EXPIRED, ch.id, STATUS_AVAILABLE) for ch in chests],
                )
        return chests

    # --- stats / admin -----------------------------------------------------
    def count_all(self, conn=None) -> int:
        with db_scope(conn) as c:
            row = c.execute("SELECT COUNT(*) AS n FROM chests").fetchone()
        return row["n"]

    def count_opened(self, conn=None) -> int:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM chests WHERE status = ?", (STATUS_OPENED,)
            ).fetchone()
        return row["n"]

    def delete_test(self, conn=None) -> int:
        """Remove admin-created test chests; returns the count deleted."""
        with db_scope(conn) as c:
            cur = c.execute("DELETE FROM chests WHERE is_test = 1")
        return cur.rowcount
