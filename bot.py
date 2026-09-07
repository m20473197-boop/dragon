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

    logger.info("Starting Dragon bot...")
    application = ApplicationBuilder().token(token).build()
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
