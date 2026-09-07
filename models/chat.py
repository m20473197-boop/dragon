"""Chat (group) repository — tracks groups the egg spawner should visit."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from database.connection import get_db


@dataclass
class Chat:
    chat_id: int
    title: Optional[str]
    last_seen: float

    @classmethod
    def from_row(cls, row) -> "Chat":
        return cls(
            chat_id=row["chat_id"],
            title=row["title"],
            last_seen=row["last_seen"],
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

    def active_chats(self, within_seconds: int, now: Optional[float] = None) -> list[Chat]:
        """Groups seen in the last ``within_seconds`` seconds."""
        now = now or time.time()
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM chats WHERE last_seen >= ? ORDER BY last_seen DESC",
                (now - within_seconds,),
            ).fetchall()
        return [Chat.from_row(r) for r in rows]
