"""Database initialization: creates tables/triggers if they do not exist."""
from __future__ import annotations

import logging
from pathlib import Path

from config import DB_PATH
from database.connection import get_db

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def init_db() -> None:
    """Execute schema.sql against the configured SQLite database."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_db() as conn:
        conn.executescript(sql)
    logger.info("Database ready at %s", DB_PATH)
