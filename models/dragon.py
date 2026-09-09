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
    DEFAULT_RARITY,
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
    rarity: str = DEFAULT_RARITY
    breeding_status: str = "idle"
    breeding_finish_time: Optional[float] = None
    parent_dragon_1: Optional[int] = None
    parent_dragon_2: Optional[int] = None
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
            # Older rows (pre-V8) have no rarity column: they are ⚪ معمولی.
            rarity=(
                row["rarity"] if "rarity" in row.keys() and row["rarity"]
                else DEFAULT_RARITY
            ),
            # V9 breeding. Older rows have no such columns: they are idle.
            breeding_status=(
                row["breeding_status"]
                if "breeding_status" in row.keys() and row["breeding_status"]
                else "idle"
            ),
            breeding_finish_time=(
                row["breeding_finish_time"]
                if "breeding_finish_time" in row.keys() else None
            ),
            parent_dragon_1=(
                row["parent_dragon_1"] if "parent_dragon_1" in row.keys() else None
            ),
            parent_dragon_2=(
                row["parent_dragon_2"] if "parent_dragon_2" in row.keys() else None
            ),
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
        rarity: str = DEFAULT_RARITY,
        parent_dragon_1: Optional[int] = None,
        parent_dragon_2: Optional[int] = None,
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
                     hunger, rarity, parent_dragon_1, parent_dragon_2,
                     last_fed_time, is_test, from_egg_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (owner_id, name, dragon_type, level, xp, hp, max_hp, power,
                 hunger, rarity, parent_dragon_1, parent_dragon_2,
                 last_fed_time, is_test, from_egg_id),
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
            rarity=rarity,
            parent_dragon_1=parent_dragon_1,
            parent_dragon_2=parent_dragon_2,
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

    def set_hp(self, dragon_id: int, hp: int, conn=None) -> bool:
        """Set current HP, clamped to [0, max_hp]. Used by the combat system.

        The dragon is never deleted or removed by this — only its HP changes.
        """
        with db_scope(conn) as c:
            cur = c.execute(
                "UPDATE dragons SET hp = MAX(0, MIN(?, max_hp)) WHERE id = ?",
                (int(hp), dragon_id),
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

    # --- breeding state (V9) -----------------------------------------------
    def mark_breeding(
        self,
        dragon_ids: tuple[int, ...],
        owner_id: int,
        finish_time: float,
        conn=None,
    ) -> bool:
        """Atomically mark several dragons as busy breeding.

        The guarded UPDATE only matches dragons that are owned by
        ``owner_id`` and currently ``idle``, and the caller checks that every
        dragon was affected. Two simultaneous confirmations therefore cannot
        both lock the same pair.
        """
        if not dragon_ids:
            return False
        placeholders = ",".join("?" for _ in dragon_ids)
        with db_scope(conn) as c:
            cur = c.execute(
                f"UPDATE dragons SET breeding_status = 'breeding', "
                f"breeding_finish_time = ? "
                f"WHERE id IN ({placeholders}) AND owner_id = ? "
                f"AND breeding_status = 'idle'",
                (finish_time, *dragon_ids, owner_id),
            )
            return cur.rowcount == len(dragon_ids)

    def clear_breeding(self, dragon_ids: tuple[int, ...], conn=None) -> int:
        """Release dragons from a ritual (they become usable again)."""
        if not dragon_ids:
            return 0
        placeholders = ",".join("?" for _ in dragon_ids)
        with db_scope(conn) as c:
            cur = c.execute(
                f"UPDATE dragons SET breeding_status = 'idle', "
                f"breeding_finish_time = NULL WHERE id IN ({placeholders})",
                tuple(dragon_ids),
            )
            return cur.rowcount

    def is_busy(self, dragon_id: int, conn=None) -> bool:
        """True while the dragon is locked in a breeding ritual."""
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT breeding_status AS s FROM dragons WHERE id = ?",
                (dragon_id,),
            ).fetchone()
        return row is not None and row["s"] == "breeding"

    def list_idle_by_owner(self, owner_id: int, conn=None) -> list["Dragon"]:
        """Dragons that are not currently busy in a ritual."""
        with db_scope(conn) as c:
            rows = c.execute(
                "SELECT * FROM dragons WHERE owner_id = ? "
                "AND breeding_status != 'breeding' ORDER BY id",
                (owner_id,),
            ).fetchall()
        return [Dragon.from_row(r) for r in rows]
