"""Cold Storage (سردخانه) tests (no Telegram needed).

Verifies that the storage service holds meat/fish, that gathering-style
deposits and feeding-style consumption go through it, and that over-spending
is blocked. Uses a throwaway SQLite file::

    python3 scripts/test_storage.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_storage_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)

from database.init_db import init_db  # noqa: E402
from game.dragons import DragonService  # noqa: E402
from game.feeding import FeedingService  # noqa: E402
from game.storage import ColdStorageService  # noqa: E402
from models.player import PlayerRepository  # noqa: E402


def main() -> None:
    init_db()
    players = PlayerRepository()
    storage = ColdStorageService(players)
    feeding = FeedingService(storage=storage)
    dragons = DragonService()

    players.get_or_create(1, "ali")

    # 1. A new player has an empty cold storage.
    c = storage.contents(1)
    assert (c.meat, c.fish) == (0, 0)
    print("✓ new cold storage is empty")

    # 2. Deposits (as performed by hunt/fish) land in storage.
    storage.deposit(1, meat=12, fish=18)
    assert (storage.contents(1).meat, storage.contents(1).fish) == (12, 18)
    assert storage.count(1, "meat") == 12 and storage.count(1, "fish") == 18
    print("✓ meat/fish deposited into cold storage")

    # 3. Feeding consumes from cold storage (meat cost 3, fish cost 5).
    dragons.create_newborn(1, "fire")
    assert feeding.feed(1, "meat").success
    assert (storage.contents(1).meat, storage.contents(1).fish) == (9, 18)
    assert feeding.feed(1, "fish").success
    assert (storage.contents(1).meat, storage.contents(1).fish) == (9, 13)
    print("✓ feeding consumes meat/fish from cold storage")

    # 4. Over-spending is rejected atomically (contents unchanged).
    assert storage.consume(1, "meat", 999) is False
    assert storage.consume(1, "fish", 999) is False
    assert (storage.contents(1).meat, storage.contents(1).fish) == (9, 13)
    print("✓ cannot consume more than stored")

    # 5. Unknown player reads as empty and feeds fail without error.
    assert storage.contents(999).meat == 0
    print("✓ unknown player reads as empty storage")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll cold storage tests passed ✅")


if __name__ == "__main__":
    main()
