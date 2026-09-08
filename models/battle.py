"""Battle model and BattleRepository (PvE fights — Version 4).

Owns all SQL for the ``battles`` table. No game rules live here; the damage
math and rewards belong to :mod:`game.combat`.

Concurrency safety:

* a partial UNIQUE index (``idx_battles_one_active``) guarantees at most one
  ``active`` battle per user at the database level, so two simultaneous
  «مبارزه» messages can never create two fights;
* every mutation is a guarded ``UPDATE ... WHERE status='active'``, so a
  button pressed twice (or after the fight ended) changes nothing.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Optional

from database.connection import db_scope

# Battle lifecycle statuses.
STATUS_ACTIVE = "active"
STATUS_WON = "won"
STATUS_LOST = "lost"
STATUS_FLED = "fled"

FINISHED_STATUSES = (STATUS_WON, STATUS_LOST, STATUS_FLED)


@dataclass
class Battle:
    battle_id: int
    user_id: int
    dragon_id: int
    enemy_id: str
    enemy_hp: int
    enemy_max_hp: int = 0
    status: str = STATUS_ACTIVE
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    turns: int = 0
    created_time: float = 0.0
    updated_time: Optional[float] = None
    finished_time: Optional[float] = None
    reward: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Battle":
        keys = row.keys()

        def opt(name, default=None):
            return row[name] if name in keys else default

        return cls(
            battle_id=row["battle_id"],
            user_id=row["user_id"],
            dragon_id=row["dragon_id"],
            enemy_id=row["enemy_id"],
            enemy_hp=row["enemy_hp"],
            enemy_max_hp=opt("enemy_max_hp", 0) or 0,
            status=row["status"],
            chat_id=opt("chat_id"),
            message_id=opt("message_id"),
            turns=opt("turns", 0) or 0,
            created_time=row["created_time"],
            updated_time=opt("updated_time"),
            finished_time=opt("finished_time"),
            reward=opt("reward"),
        )

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE

    def reward_dict(self) -> dict:
        """The stored reward snapshot as a dict ({} when absent/invalid)."""
        if not self.reward:
            return {}
        try:
            return json.loads(self.reward)
        except (ValueError, TypeError):
            return {}


class BattleRepository:
    # --- creating ----------------------------------------------------------
    def start(
        self,
        user_id: int,
        dragon_id: int,
        enemy_id: str,
        enemy_hp: int,
        enemy_max_hp: int,
        created_time: float,
        chat_id: Optional[int] = None,
        conn=None,
    ) -> Optional[Battle]:
        """Create an active battle, or return ``None`` if one already exists.

        The unique partial index makes this race-free: if two presses arrive at
        the same instant, one INSERT raises IntegrityError and loses.
        """
        try:
            with db_scope(conn) as c:
                cur = c.execute(
                    """
                    INSERT INTO battles
                        (user_id, dragon_id, chat_id, enemy_id, enemy_hp,
                         enemy_max_hp, status, turns, created_time, updated_time)
                    SELECT ?, ?, ?, ?, ?, ?, ?, 0, ?, ?
                     WHERE NOT EXISTS (
                         SELECT 1 FROM battles WHERE user_id = ? AND status = ?
                     )
                    """,
                    (
                        user_id, dragon_id, chat_id, enemy_id, enemy_hp,
                        enemy_max_hp, STATUS_ACTIVE, created_time, created_time,
                        user_id, STATUS_ACTIVE,
                    ),
                )
                battle_id = cur.lastrowid if cur.rowcount == 1 else None
        except sqlite3.IntegrityError:
            return None
        if battle_id is None:
            return None
        return Battle(
            battle_id=battle_id,
            user_id=user_id,
            dragon_id=dragon_id,
            chat_id=chat_id,
            enemy_id=enemy_id,
            enemy_hp=enemy_hp,
            enemy_max_hp=enemy_max_hp,
            status=STATUS_ACTIVE,
            created_time=created_time,
            updated_time=created_time,
        )

    # --- reading -----------------------------------------------------------
    def get(self, battle_id: int, conn=None) -> Optional[Battle]:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM battles WHERE battle_id = ?", (battle_id,)
            ).fetchone()
        return Battle.from_row(row) if row is not None else None

    def get_active_for_user(self, user_id: int, conn=None) -> Optional[Battle]:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM battles WHERE user_id = ? AND status = ? "
                "ORDER BY battle_id DESC LIMIT 1",
                (user_id, STATUS_ACTIVE),
            ).fetchone()
        return Battle.from_row(row) if row is not None else None

    # --- mutating ----------------------------------------------------------
    def set_message_id(self, battle_id: int, message_id: int, conn=None) -> None:
        with db_scope(conn) as c:
            c.execute(
                "UPDATE battles SET message_id = ? WHERE battle_id = ?",
                (message_id, battle_id),
            )

    def apply_turn(
        self,
        battle_id: int,
        enemy_hp: int,
        now: float,
        expected_turns: int,
        conn=None,
    ) -> bool:
        """Store the enemy HP after one exchange.

        Guarded on both ``status='active'`` and the turn counter, so two taps
        of «حمله» that arrive together can only apply one turn.
        """
        with db_scope(conn) as c:
            cur = c.execute(
                """
                UPDATE battles
                   SET enemy_hp = ?, turns = turns + 1, updated_time = ?
                 WHERE battle_id = ? AND status = ? AND turns = ?
                """,
                (max(0, enemy_hp), now, battle_id, STATUS_ACTIVE, expected_turns),
            )
            return cur.rowcount == 1

    def finish(
        self,
        battle_id: int,
        status: str,
        now: float,
        enemy_hp: Optional[int] = None,
        reward: Optional[dict] = None,
        conn=None,
    ) -> bool:
        """Close an active battle. Returns False if it was already closed."""
        if status not in FINISHED_STATUSES:
            raise ValueError(f"Unknown finish status: {status!r}")
        reward_json = (
            json.dumps(reward, ensure_ascii=False) if reward is not None else None
        )
        with db_scope(conn) as c:
            if enemy_hp is None:
                cur = c.execute(
                    """
                    UPDATE battles
                       SET status = ?, finished_time = ?, updated_time = ?,
                           reward = COALESCE(?, reward)
                     WHERE battle_id = ? AND status = ?
                    """,
                    (status, now, now, reward_json, battle_id, STATUS_ACTIVE),
                )
            else:
                cur = c.execute(
                    """
                    UPDATE battles
                       SET status = ?, enemy_hp = ?, finished_time = ?,
                           updated_time = ?, reward = COALESCE(?, reward)
                     WHERE battle_id = ? AND status = ?
                    """,
                    (
                        status, max(0, enemy_hp), now, now, reward_json,
                        battle_id, STATUS_ACTIVE,
                    ),
                )
            return cur.rowcount == 1

    def expire_older_than(self, cutoff: float, conn=None) -> list[Battle]:
        """Abandon active battles last touched before ``cutoff``; returns them."""
        with db_scope(conn) as c:
            rows = c.execute(
                "SELECT * FROM battles WHERE status = ? "
                "AND COALESCE(updated_time, created_time) < ?",
                (STATUS_ACTIVE, cutoff),
            ).fetchall()
            battles = [Battle.from_row(r) for r in rows]
            if battles:
                c.executemany(
                    "UPDATE battles SET status = ?, finished_time = ? "
                    "WHERE battle_id = ? AND status = ?",
                    [(STATUS_FLED, cutoff, b.battle_id, STATUS_ACTIVE) for b in battles],
                )
        return battles

    # --- stats / admin -----------------------------------------------------
    def count_all(self, conn=None) -> int:
        with db_scope(conn) as c:
            row = c.execute("SELECT COUNT(*) AS n FROM battles").fetchone()
        return row["n"]

    def count_by_status(self, status: str, conn=None) -> int:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM battles WHERE status = ?", (status,)
            ).fetchone()
        return row["n"]
