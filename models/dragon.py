"""Dragon model and DragonRepository (born from hatched eggs)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from database.connection import db_scope


@dataclass
class Dragon:
    id: int
    owner_id: int
    dragon_type: str
    from_egg_id: Optional[int] = None
    born_at: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Dragon":
        return cls(
            id=row["id"],
            owner_id=row["owner_id"],
            dragon_type=row["dragon_type"],
            from_egg_id=row["from_egg_id"],
            born_at=row["born_at"],
        )


class DragonRepository:
    def create(
        self,
        owner_id: int,
        dragon_type: str,
        from_egg_id: Optional[int],
        conn=None,
    ) -> Dragon:
        with db_scope(conn) as c:
            cur = c.execute(
                """
                INSERT INTO dragons (owner_id, dragon_type, from_egg_id)
                VALUES (?, ?, ?)
                """,
                (owner_id, dragon_type, from_egg_id),
            )
            dragon_id = cur.lastrowid
        return Dragon(
            id=dragon_id, owner_id=owner_id, dragon_type=dragon_type, from_egg_id=from_egg_id
        )

    def count_by_owner(self, owner_id: int, conn=None) -> int:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT COUNT(*) AS c FROM dragons WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
        return row["c"]

    def list_by_owner(self, owner_id: int, conn=None) -> list[Dragon]:
        with db_scope(conn) as c:
            rows = c.execute(
                "SELECT * FROM dragons WHERE owner_id = ? ORDER BY id DESC",
                (owner_id,),
            ).fetchall()
        return [Dragon.from_row(r) for r in rows]
