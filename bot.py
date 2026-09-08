"""Dragon — a Telegram group bot game.

Entry point: initializes the SQLite database and starts long-polling.

Run with::

    python bot.py
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ApplicationBuilder

from config import require_token
from database.init_db import init_db
from database.migrate import run_migrations
from handlers import register_all

logging.basicConfig(
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
# APScheduler can be noisy; keep it at WARNING.
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger("dragon")


def main() -> None:
    token = require_token()

    # Make sure tables exist before any update arrives.
    init_db()
    # Bring older databases up to date (additive, idempotent).
    run_migrations()

    logger.info("Starting Dragon bot...")
    # Generous HTTP timeouts: slow Telegram responses used to raise TimedOut
    # inside scheduled jobs. Sending is additionally retried in
    # handlers.chests.safe_send_message.
    application = (
        ApplicationBuilder()
        .token(token)
        .connect_timeout(15.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(15.0)
        .get_updates_read_timeout(40.0)
        .build()
    )
    register_all(application)

    # Run until Ctrl+C. drop_pending_updates avoids processing old commands
    # after a restart (which could otherwise trigger stale cooldown/claim
    # actions).
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
