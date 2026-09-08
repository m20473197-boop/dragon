"""Egg spawn cooldown tests.

Checks the round's requirements:
  * after an egg spawns in a group, a cooldown starts,
  * no second egg spawns until the cooldown finishes,
  * simultaneous attempts cannot both spawn,
  * the last spawn time is stored in the database (survives a restart),
  * groups have independent timers,
  * EGG_SPAWN_INTERVAL is configurable (production vs testing),
  * collecting/storing/hatching eggs still work untouched.

Run: python3 scripts/test_spawn_cooldown.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_spawn_cooldown.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)

import config  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game import spawn_settings  # noqa: E402
from game.eggs import EggService  # noqa: E402
from models.chat import ChatRepository  # noqa: E402
from models.egg import EggRepository  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

init_db()
run_migrations()

GROUP_A = -100
GROUP_B = -200
HOUR = 3600.0


def main() -> None:
    chats = ChatRepository()
    eggs = EggRepository()
    players = PlayerRepository()
    egg_service = EggService(eggs=eggs, players=players)

    # 1. The interval is configurable and defaults to 2 hours.
    assert config.EGG_SPAWN_INTERVAL == 2 * HOUR, config.EGG_SPAWN_INTERVAL
    assert spawn_settings.get_interval() == 2 * HOUR
    spawn_settings.set_interval(60)                     # testing value
    assert spawn_settings.get_interval() == 60 and spawn_settings.active()
    spawn_settings.set_interval(None)                   # back to production
    assert spawn_settings.get_interval() == 2 * HOUR and not spawn_settings.active()
    print("✓ EGG_SPAWN_INTERVAL configurable (7200 production / 60 testing)")

    interval = int(2 * HOUR)
    noon = 1_700_000_000.0                              # a fixed "12:00"

    chats.touch(GROUP_A, "Group A", now=noon)
    chats.touch(GROUP_B, "Group B", now=noon)

    # 2. The first spawn is allowed and starts the cooldown.
    assert chats.try_claim_egg_spawn(GROUP_A, interval, now=noon) is True
    stored = chats.get(GROUP_A)
    assert stored.last_egg_spawn_time == noon
    print("✓ first egg spawns and starts the group's cooldown")

    # 3. No second egg during the cooldown (12:00 -> 14:00).
    for offset in (1, 60, 30 * 60, interval - 1):
        assert chats.try_claim_egg_spawn(GROUP_A, interval, now=noon + offset) is False
    assert chats.get(GROUP_A).last_egg_spawn_time == noon   # unchanged
    print("✓ no further egg during the 2-hour cooldown")

    # 4. After the interval, a new egg may spawn and the timer restarts.
    assert chats.try_claim_egg_spawn(GROUP_A, interval, now=noon + interval) is True
    assert chats.get(GROUP_A).last_egg_spawn_time == noon + interval
    assert chats.try_claim_egg_spawn(GROUP_A, interval, now=noon + interval + 5) is False
    print("✓ after the interval a new egg spawns and the timer restarts")

    # 5. Groups are independent (Group A at 12:00, Group B at 12:30).
    half = noon + 30 * 60
    assert chats.try_claim_egg_spawn(GROUP_B, interval, now=half) is True
    assert chats.get(GROUP_B).last_egg_spawn_time == half
    assert chats.get(GROUP_A).last_egg_spawn_time == noon + interval  # untouched
    # B is on cooldown until 14:30 even though A already spawned again.
    assert chats.try_claim_egg_spawn(GROUP_B, interval, now=half + interval - 1) is False
    assert chats.try_claim_egg_spawn(GROUP_B, interval, now=half + interval) is True
    print("✓ each group has its own independent timer (A 12:00 / B 12:30)")

    # 6. Remaining-time helper reports the countdown.
    chats.touch(-300, "Group C", now=noon)
    assert chats.egg_spawn_remaining(-300, interval, now=noon) == 0.0   # never spawned
    chats.try_claim_egg_spawn(-300, interval, now=noon)
    assert chats.egg_spawn_remaining(-300, interval, now=noon) == interval
    assert chats.egg_spawn_remaining(-300, interval, now=noon + interval) == 0.0
    print("✓ remaining cooldown is reported correctly")

    # 7. The timestamp lives in the database -> survives a restart.
    fresh_repo = ChatRepository()          # simulates a new process
    assert fresh_repo.get(GROUP_B).last_egg_spawn_time == half + interval
    assert fresh_repo.try_claim_egg_spawn(GROUP_B, interval, now=half + interval + 10) is False
    import sqlite3

    raw = sqlite3.connect(_tmp_db).execute(
        "SELECT last_egg_spawn_time FROM chats WHERE chat_id = ?", (GROUP_B,)
    ).fetchone()
    assert raw[0] == half + interval
    print("✓ last spawn time persisted in the database (survives a restart)")

    # 8. Simultaneous attempts: only one can claim the slot.
    import threading

    chats.touch(-400, "Group D", now=noon)
    wins = []
    lock = threading.Lock()

    def _claim():
        ok = ChatRepository().try_claim_egg_spawn(-400, interval, now=noon)
        with lock:
            wins.append(ok)

    threads = [threading.Thread(target=_claim) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for w in wins if w) == 1, wins
    print("✓ 12 simultaneous attempts -> exactly one egg slot claimed")

    # 9. A released claim (egg not actually created) restores the old time.
    chats.touch(-500, "Group E", now=noon)
    assert chats.try_claim_egg_spawn(-500, interval, now=noon) is True
    chats.release_egg_spawn(-500, None)            # rollback
    assert chats.get(-500).last_egg_spawn_time is None
    assert chats.try_claim_egg_spawn(-500, interval, now=noon) is True
    print("✓ a failed spawn releases the slot instead of locking the group out")

    # 10. Existing egg systems are untouched: spawn, claim, store and hatch.
    players.get_or_create(1, "ali")
    egg = egg_service.spawn_wild_egg(GROUP_A)
    assert egg is not None and egg.status == "available"
    # The one-egg-per-group rule still applies on top of the cooldown.
    assert egg_service.spawn_wild_egg(GROUP_A) is None
    claimed, _ = egg_service.claim_egg(egg.id, 1)
    assert claimed is not None and claimed.owner_id == 1
    assert claimed.status == "incubating"
    assert players.get(1).eggs == 1                       # egg storage intact
    from database.connection import get_db

    with get_db() as conn:
        conn.execute("UPDATE eggs SET hatch_time = 1.0 WHERE id = ?", (egg.id,))
    events = egg_service.process_hatchings()
    assert any(e.egg.id == egg.id for e in events)        # hatching intact
    assert players.get(1).dragons == 1
    print("✓ egg collecting, storage and hatching still work unchanged")

    # 11. A testing interval of 60s behaves the same, just faster.
    spawn_settings.set_interval(60)
    chats.touch(-600, "Group F", now=noon)
    assert chats.try_claim_egg_spawn(-600, spawn_settings.get_interval(), now=noon) is True
    assert chats.try_claim_egg_spawn(-600, spawn_settings.get_interval(), now=noon + 59) is False
    assert chats.try_claim_egg_spawn(-600, spawn_settings.get_interval(), now=noon + 60) is True
    spawn_settings.set_interval(None)
    print("✓ testing interval (60s) works the same way")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll egg spawn cooldown tests passed ✅")


if __name__ == "__main__":
    main()
