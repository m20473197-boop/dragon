"""SQLite connection helpers.

A fresh connection is opened per operation (SQLite is cheap for this) which
keeps the bot safe under python-telegram-bot's concurrent async updates.

Connections use WAL journaling and a busy timeout so that simultaneous writes
(e.g. several users claiming eggs at once) wait for each other instead of
raising "database is locked".
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

from config import DB_PATH

# How long (ms) a write waits for a lock before failing.
BUSY_TIMEOUT_MS = 5000


def create_connection() -> sqlite3.Connection:
    """Create a new SQLite connection with sensible pragmas."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS};")
    # WAL + NORMAL allow concurrent readers while a write is in progress and
    # are durable enough for a game bot (no corruption, only possible loss of
    # the last transaction on OS-level crash).
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Yield a connection, committing on success and rolling back on error.

    Example::

        with get_db() as conn:
            conn.execute("INSERT INTO players ...")
    """
    conn = create_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def db_scope(conn: Optional[sqlite3.Connection] = None) -> Iterator[sqlite3.Connection]:
    """Run inside ``conn`` if given, otherwise open a new transaction.

    Lets a service compose several repository calls inside one atomic
    transaction: when it passes its own connection, nothing is committed or
    closed here (the outer ``with get_db()`` owns that); when no connection is
    passed, behaviour is identical to :func:`get_db`.

    Example::

        with get_db() as conn:           # one transaction for both writes
            repo.add_resources(..., conn=conn)
            eggs.create(..., conn=conn)
    """
    if conn is not None:
        yield conn
        return
    with get_db() as owned:
        yield owned
