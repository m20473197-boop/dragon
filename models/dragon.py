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
    DRAGON_DEFAULT_HUNGER,
    DRAGON_DEFAULT_LEVEL,
    DRAGON_DEFAULT_MAX_HP,
    DRAGON_DEFAULT_POWER,
    DRAGON_DEFAULT_XP,
    XP_PER_LEVEL_BASE,
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
    hunger: int = DRAGON_DEFAULT_HUNGER
    last_fed_time: Optional[float] = None
    is_test: int = 0
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
            hunger=row["hunger"],
            last_fed_time=row["last_fed_time"],
            is_test=row["is_test"] if "is_test" in row.keys() else 0,
            from_egg_id=row["from_egg_id"],
            born_at=row["born_at"],
        )

    def xp_required_for_next_level(self) -> int:
        """XP needed to advance from the current level to the next one."""
        return self.level * XP_PER_LEVEL_BASE


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
        hunger: int = DRAGON_DEFAULT_HUNGER,
        last_fed_time: Optional[float] = None,
        is_test: int = 0,
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
                    (owner_id, name, dragon_type, level, xp, hp, max_hp, power,
                     hunger, last_fed_time, is_test, from_egg_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (owner_id, name, dragon_type, level, xp, hp, max_hp, power,
                 hunger, last_fed_time, is_test, from_egg_id),
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
            hunger=hunger,
            last_fed_time=last_fed_time,
            is_test=is_test,
            from_egg_id=from_egg_id,
        )

    def count_all(self, conn=None) -> int:
        with db_scope(conn) as c:
            row = c.execute("SELECT COUNT(*) AS n FROM dragons").fetchone()
        return row["n"]

    def delete_test(self, conn=None) -> int:
        """Remove admin-created test dragons; returns the count deleted."""
        with db_scope(conn) as c:
            ids = [
                r["owner_id"]
                for r in c.execute(
                    "SELECT owner_id FROM dragons WHERE is_test = 1"
                ).fetchall()
            ]
            # Drop the active-dragon pointer for test dragons about to vanish.
            c.execute(
                "UPDATE players SET active_dragon_id = NULL WHERE active_dragon_id IN "
                "(SELECT id FROM dragons WHERE is_test = 1)"
            )
            cur = c.execute("DELETE FROM dragons WHERE is_test = 1")
            deleted = cur.rowcount
            # Adjust the per-owner dragon counters for the removed test dragons.
            if ids:
                c.executemany(
                    "UPDATE players SET dragons = MAX(0, dragons - 1) WHERE user_id = ?",
                    [(uid,) for uid in ids],
                )
        return deleted

    def get(self, dragon_id: int, conn=None) -> Optional[Dragon]:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM dragons WHERE id = ?", (dragon_id,)
            ).fetchone()
        return Dragon.from_row(row) if row is not None else None

    def get_owned(self, dragon_id: int, owner_id: int, conn=None) -> Optional[Dragon]:
        """Fetch a dragon only if it belongs to the given owner."""
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM dragons WHERE id = ? AND owner_id = ?",
                (dragon_id, owner_id),
            ).fetchone()
        return Dragon.from_row(row) if row is not None else None

    def set_name(self, dragon_id: int, owner_id: int, name: str, conn=None) -> bool:
        """Rename a dragon. Returns False if it is not owned by ``owner_id``."""
        with db_scope(conn) as c:
            cur = c.execute(
                "UPDATE dragons SET name = ? WHERE id = ? AND owner_id = ?",
                (name, dragon_id, owner_id),
            )
            return cur.rowcount == 1

    def update_growth(
        self,
        dragon_id: int,
        level: int,
        xp: int,
        hp: int,
        max_hp: int,
        power: int,
        conn=None,
    ) -> None:
        """Persist new level/xp/hp/max_hp/power after XP gain / level up."""
        with db_scope(conn) as c:
            c.execute(
                """
                UPDATE dragons
                   SET level = ?, xp = ?, hp = ?, max_hp = ?, power = ?
                 WHERE id = ?
                """,
                (level, xp, hp, max_hp, power, dragon_id),
            )

    def update_full_stats(
        self,
        dragon_id: int,
        level: int,
        xp: int,
        hp: int,
        max_hp: int,
        power: int,
        hunger: int,
        last_fed_time: Optional[float],
        conn=None,
    ) -> None:
        """Persist all dragon stats (used after feeding)."""
        with db_scope(conn) as c:
            c.execute(
                """
                UPDATE dragons
                   SET level = ?, xp = ?, hp = ?, max_hp = ?, power = ?,
                       hunger = ?, last_fed_time = ?
                 WHERE id = ?
                """,
                (level, xp, hp, max_hp, power, hunger, last_fed_time, dragon_id),
            )

    def newest_for_owner(self, owner_id: int, conn=None) -> Optional[Dragon]:
        """The owner's most recently hatched dragon, or None."""
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM dragons WHERE owner_id = ? ORDER BY id DESC LIMIT 1",
                (owner_id,),
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
