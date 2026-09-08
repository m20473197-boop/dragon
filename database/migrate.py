"""Tiny additive migrations for existing databases.

The schema in ``schema.sql`` uses ``CREATE TABLE IF NOT EXISTS``, so new
installs always get the latest shape, but an already-existing table is never
altered by it. These migrations add missing columns to older databases so the
bot can upgrade in place. They are idempotent and safe to run on every start.
"""
from __future__ import annotations

import logging

from config import (
    DEFAULT_DRAGON_NAME,
    DRAGON_DEFAULT_HP,
    DRAGON_DEFAULT_HUNGER,
    DRAGON_DEFAULT_LEVEL,
    DRAGON_DEFAULT_MAX_HP,
    DRAGON_DEFAULT_POWER,
    DRAGON_DEFAULT_XP,
)
from database.connection import get_db

logger = logging.getLogger(__name__)

# table -> {column: column definition for ALTER TABLE ADD COLUMN}
_EXPECTED_COLUMNS: dict[str, dict[str, str]] = {
    "players": {
        "hunt_count": "INTEGER NOT NULL DEFAULT 0",
        "fishing_count": "INTEGER NOT NULL DEFAULT 0",
        "active_dragon_id": "INTEGER",
        "obsidian": "INTEGER NOT NULL DEFAULT 0",
        "aether": "INTEGER NOT NULL DEFAULT 0",
    },
    "chats": {
        "last_egg_spawn_time": "REAL",
    },
    "eggs": {
        "is_test": "INTEGER NOT NULL DEFAULT 0",
    },
    "dragons": {
        "name": f"TEXT NOT NULL DEFAULT '{DEFAULT_DRAGON_NAME}'",
        "level": f"INTEGER NOT NULL DEFAULT {DRAGON_DEFAULT_LEVEL}",
        "xp": f"INTEGER NOT NULL DEFAULT {DRAGON_DEFAULT_XP}",
        "hp": f"INTEGER NOT NULL DEFAULT {DRAGON_DEFAULT_HP}",
        "max_hp": f"INTEGER NOT NULL DEFAULT {DRAGON_DEFAULT_MAX_HP}",
        "power": f"INTEGER NOT NULL DEFAULT {DRAGON_DEFAULT_POWER}",
        "hunger": f"INTEGER NOT NULL DEFAULT {DRAGON_DEFAULT_HUNGER}",
        "last_fed_time": "REAL",
    },
}


def _existing_columns(conn, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def run_migrations() -> None:
    """Add any missing columns to tables created by older versions."""
    with get_db() as conn:
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table, columns in _EXPECTED_COLUMNS.items():
            if table not in tables:
                continue  # fresh DB; schema.sql created it with all columns
            present = _existing_columns(conn, table)
            for column, definition in columns.items():
                if column not in present:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                    logger.info("Migrated %s: added column %s", table, column)
