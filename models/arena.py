"""Arena battle history and its repository (Version 7 — PvP).

Replaces the Version-4 PvE ``battles`` table. An arena duel is resolved in a
single call (the whole fight is simulated at once), so unlike the old system
there is no "active battle" row to guard — each row here is a *finished*
duel kept for the result screen and for stats.

Owns all SQL for the ``arena_battles`` table; the fight rules live in
:mod:`game.arena`.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Optional

from database.connection import db_scope


@dataclass
class ArenaBattle:
    battle_id: int
    challenger_id: int
    opponent_id: int
    challenger_dragon_id: int
    opponent_dragon_id: int
    winner_id: int
    turns: int = 0
    chat_id: Optional[int] = None
    log: list = field(default_factory=list)
    reward: dict = field(default_factory=dict)
    created_time: float = 0.0

    @classmethod
    def from_row(cls, row) -> "ArenaBattle":
        keys = row.keys()

        def _json(name, default):
            if name not in keys or row[name] is None:
                return default
            try:
                return json.loads(row[name])
            except (ValueError, TypeError):
                return default

        return cls(
            battle_id=row["battle_id"],
            challenger_id=row["challenger_id"],
            opponent_id=row["opponent_id"],
            challenger_dragon_id=row["challenger_dragon_id"],
            opponent_dragon_id=row["opponent_dragon_id"],
            winner_id=row["winner_id"],
            turns=row["turns"] if "turns" in keys else 0,
            chat_id=row["chat_id"] if "chat_id" in keys else None,
            log=_json("log", []),
            reward=_json("reward", {}),
            created_time=row["created_time"] if "created_time" in keys else 0.0,
        )


class ArenaBattleRepository:
    """Append-only history of arena duels."""

    def record(
        self,
        challenger_id: int,
        opponent_id: int,
        challenger_dragon_id: int,
        opponent_dragon_id: int,
        winner_id: int,
        turns: int = 0,
        chat_id: Optional[int] = None,
        log: Optional[list] = None,
        reward: Optional[dict] = None,
        now: Optional[float] = None,
        conn=None,
    ) -> int:
        """Store one finished duel and return its id."""
        now = now if now is not None else time.time()
        with db_scope(conn) as c:
            cur = c.execute(
                "INSERT INTO arena_battles ("
                "challenger_id, opponent_id, challenger_dragon_id, "
                "opponent_dragon_id, winner_id, turns, chat_id, log, reward, "
                "created_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    challenger_id,
                    opponent_id,
                    challenger_dragon_id,
                    opponent_dragon_id,
                    winner_id,
                    turns,
                    chat_id,
                    json.dumps(log or [], ensure_ascii=False),
                    json.dumps(reward or {}, ensure_ascii=False),
                    now,
                ),
            )
            return int(cur.lastrowid)

    def get(self, battle_id: int, conn=None) -> Optional[ArenaBattle]:
        with db_scope(conn) as c:
            row = c.execute(
                "SELECT * FROM arena_battles WHERE battle_id = ?", (battle_id,)
            ).fetchone()
        return None if row is None else ArenaBattle.from_row(row)

    def recent_for_player(
        self, user_id: int, limit: int = 10, conn=None
    ) -> list[ArenaBattle]:
        with db_scope(conn) as c:
            rows = c.execute(
                "SELECT * FROM arena_battles WHERE challenger_id = ? OR opponent_id = ? "
                "ORDER BY created_time DESC LIMIT ?",
                (user_id, user_id, limit),
            ).fetchall()
        return [ArenaBattle.from_row(r) for r in rows]

    def count_all(self, conn=None) -> int:
        with db_scope(conn) as c:
            row = c.execute("SELECT COUNT(*) AS n FROM arena_battles").fetchone()
        return int(row["n"]) if row is not None else 0
