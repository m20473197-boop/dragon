"""Dragon model and DragonRepository (born from hatched eggs).

A dragon's full data set lives here: identity (id, owner), appearance
(name/type) and stats (level, xp, hp, max_hp, power). The repository owns all
SQL for the ``dragons`` table.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config import (
    DEFAULT_DRAGON_NAME,
    DRAGON_DEFAULT_HP,
    DRAGON_DEFAULT_LEVEL,
    DRAGON_DEFAULT_MAX_HP,
    DRAGON_DEFAULT_POWER,
    DRAGON_DEFAULT_XP,
)
from database.connection import db_scope


@dataclass
class Dragon:
    id: int
    owner_id: int
    dragon_type: str
    name: str = DEFAULT_DRAGON_NAME
    level: int = DRAGON_DEFAULT_LEVEL
    xp: int = DRAGON_DEFAULT_XP
    hp: int = DRAGON_DEFAULT_HP
    max_hp: int = DRAGON_DEFAULT_MAX_HP
    power: int = DRAGON_DEFAULT_POWER
    from_egg_id: Optional[int] = None
    born_at: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Dragon":
        return cls(
            id=row["id"],
            owner_id=row["owner_id"],
            dragon_type=row["dragon_type"],
            name=row["name"],
            level=row["level"],
            xp=row["xp"],
            hp=row["hp"],
            max_hp=row["max_hp"],
            power=row["power"],
            from_egg_id=row["from_egg_id"],
            born_at=row["born_at"],
        )


class DragonRepository:
    def create(
        self,
        owner_id: int,
        dragon_type: str,
        from_egg_id: Optional[int],
        name: str = DEFAULT_DRAGON_NAME,
        level: int = DRAGON_DEFAULT_LEVEL,
        xp: int = DRAGON_DEFAULT_XP,
        hp: int = DRAGON_DEFAULT_HP,
        max_hp: int = DRAGON_DEFAULT_MAX_HP,
        power: int = DRAGON_DEFAULT_POWER,
        conn=None,
    ) -> Dragon:
        """Insert a new dragon with explicit (default) stats.

        Stats are passed in (rather than relying on column defaults) so the
        returned object exactly matches what was stored.
        """
        with db_scope(conn) as c:
            cur = c.execute(
                """
                INSERT INTO dragons
                    (owner_id, name, dragon_type, level, xp, hp, max_hp, power, from_egg_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (owner_id, name, dragon_type, level, xp, hp, max_hp, power, from_egg_id),
            )
            dragon_id = cur.lastrowid
        return Dragon(
            id=dragon_id,
            owner_id=owner_id,
            dragon_type=dragon_type,
            name=name,
            level=level,
            xp=xp,
            hp=hp,
            max_hp=max_hp,
            power=power,
            from_egg_id=from_egg_id,
        )

    def get(self, dragon_id: int, conn=None) -> Optional[Dragon]:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM dragons WHERE id = ?", (dragon_id,)
            ).fetchone()
        return Dragon.from_row(row) if row is not None else None

    def count_by_owner(self, owner_id: int, conn=None) -> int:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT COUNT(*) AS c FROM dragons WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()
        return row["c"]

    def list_by_owner(self, owner_id: int, conn=None) -> list[Dragon]:
        """All of the owner's dragons, newest first."""
        with db_scope(conn) as c:
            rows = c.execute(
                "SELECT * FROM dragons WHERE owner_id = ? ORDER BY id DESC",
                (owner_id,),
            ).fetchall()
        return [Dragon.from_row(r) for r in rows]
