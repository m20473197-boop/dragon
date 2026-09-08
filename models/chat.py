"""Chat (group) repository — tracks groups the egg spawner should visit."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from database.connection import db_scope, get_db


@dataclass
class Chat:
    chat_id: int
    title: Optional[str]
    last_seen: float
    last_egg_spawn_time: Optional[float] = None

    @classmethod
    def from_row(cls, row) -> "Chat":
        keys = row.keys()
        return cls(
            chat_id=row["chat_id"],
            title=row["title"],
            last_seen=row["last_seen"],
            last_egg_spawn_time=(
                row["last_egg_spawn_time"] if "last_egg_spawn_time" in keys else None
            ),
        )


class ChatRepository:
    def touch(self, chat_id: int, title: Optional[str], now: Optional[float] = None) -> None:
        """Record activity in a group (insert or update)."""
        now = now or time.time()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO chats (chat_id, title, last_seen)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title     = excluded.title,
                    last_seen  = excluded.last_seen
                """,
                (chat_id, title, now),
            )

    # --- egg spawn cooldown (one egg per group per interval) ---------------
    def try_claim_egg_spawn(
        self, chat_id: int, interval_seconds: int, now: Optional[float] = None, conn=None
    ) -> bool:
        """Atomically reserve this group's egg-spawn slot.

        Returns True only when the group's cooldown has elapsed, and stamps
        ``last_egg_spawn_time`` in the same statement. Because the check and
        the write are one guarded UPDATE, two concurrent spawner ticks can
        never both win, so at most one egg spawns per interval per group.
        The timestamp lives in the database, so the timer survives a restart,
        and every group has its own independent cooldown.
        """
        now = now if now is not None else time.time()
        with db_scope(conn) as c:
            cur = c.execute(
                """
                UPDATE chats
                   SET last_egg_spawn_time = ?
                 WHERE chat_id = ?
                   AND (last_egg_spawn_time IS NULL
                        OR last_egg_spawn_time <= ?)
                """,
                (now, chat_id, now - interval_seconds),
            )
            return cur.rowcount == 1

    def release_egg_spawn(
        self, chat_id: int, previous: Optional[float], conn=None
    ) -> None:
        """Undo a claim (used when the egg could not actually be created)."""
        with db_scope(conn) as c:
            c.execute(
                "UPDATE chats SET last_egg_spawn_time = ? WHERE chat_id = ?",
                (previous, chat_id),
            )

    def get(self, chat_id: int, conn=None) -> Optional[Chat]:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM chats WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return Chat.from_row(row) if row is not None else None

    def egg_spawn_remaining(
        self, chat_id: int, interval_seconds: int, now: Optional[float] = None
    ) -> float:
        """Seconds left before this group may spawn another egg (0 if ready)."""
        now = now if now is not None else time.time()
        chat = self.get(chat_id)
        if chat is None or chat.last_egg_spawn_time is None:
            return 0.0
        return max(0.0, (chat.last_egg_spawn_time + interval_seconds) - now)

    def count_all(self, conn=None) -> int:
        with db_scope(conn) as c:
            row = c.execute("SELECT COUNT(*) AS n FROM chats").fetchone()
        return row["n"]

    def active_chats(self, within_seconds: int, now: Optional[float] = None) -> list[Chat]:
        """Groups seen in the last ``within_seconds`` seconds."""
        now = now or time.time()
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM chats WHERE last_seen >= ? ORDER BY last_seen DESC",
                (now - within_seconds,),
            ).fetchall()
        return [Chat.from_row(r) for r in rows]
