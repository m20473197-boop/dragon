"""Concurrency / atomicity tests (no Telegram needed).

Verifies the stability guarantees added in the review:

* Two hunts at the same instant can only succeed once (no duplicate rewards).
* Two claims at the same instant can only succeed once (one winner).
* Re-running the hatch sweep can never produce two dragons from one egg
  (idempotent hatching).
* Per-group spawn never duplicates an available egg.

Uses a throwaway SQLite file::

    python3 scripts/test_atomicity.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_atomicity_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)

from database.connection import get_db  # noqa: E402
from database.init_db import init_db  # noqa: E402
from game import actions  # noqa: E402
from game.eggs import EggService  # noqa: E402
from models.player import PlayerRepository  # noqa: E402


def main() -> None:
    init_db()
    repo = PlayerRepository()
    svc = EggService()

    # --- 1. Concurrent hunts: exactly one reward -------------------------
    repo.get_or_create(1, "hunter")
    results: list[bool] = []
    lock = threading.Lock()

    def do_hunt() -> None:
        r = actions.hunt(repo, repo.get(1))  # fresh read each thread
        with lock:
            results.append(r.success)

    threads = [threading.Thread(target=do_hunt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = sum(results)
    meat_after = repo.get(1).meat
    assert successes == 1, f"expected 1 successful hunt, got {successes}"
    assert 1 <= meat_after <= 9, f"expected one meat grant, got {meat_after}"
    print(f"✓ {len(threads)} simultaneous hunts -> 1 reward (+{meat_after} meat)")

    # --- 2. Concurrent claims: exactly one winner ------------------------
    CHAT = -100200300
    for uid in range(2, 12):
        repo.get_or_create(uid, f"u{uid}")
    egg = svc.spawn_wild_egg(CHAT)
    assert egg is not None
    # While that egg waits unclaimed, no second available egg may appear.
    assert svc.spawn_wild_egg(CHAT) is None, "duplicate available egg while one waits"

    winners: list[int] = []
    wlock = threading.Lock()

    def do_claim(uid: int) -> None:
        claimed, _current = svc.claim_egg(egg.id, uid)
        if claimed is not None:
            with wlock:
                winners.append(uid)

    claim_threads = [threading.Thread(target=do_claim, args=(uid,)) for uid in range(2, 12)]
    for t in claim_threads:
        t.start()
    for t in claim_threads:
        t.join()

    assert len(winners) == 1, f"expected exactly 1 winner, got {winners}"
    assert svc.eggs.get(egg.id).owner_id == winners[0]
    print(f"✓ {len(claim_threads)} simultaneous claims -> 1 winner (user {winners[0]})")

    # --- 3. Idempotent hatching: one dragon per egg ----------------------
    winner = winners[0]
    # Force the egg past its hatch time.
    due = svc.eggs.list_active_by_owner(winner)[0]
    with get_db() as conn:
        conn.execute("UPDATE eggs SET hatch_time = 0 WHERE id = ?", (due.id,))

    first = svc.process_hatchings()
    second = svc.process_hatchings()
    assert len(first) == 1, f"first sweep should hatch 1 egg, got {len(first)}"
    assert len(second) == 0, f"second sweep must not re-hatch, got {len(second)}"
    assert svc.dragons.count_by_owner(winner) == 1, "exactly one dragon for the egg"
    print("✓ double hatch sweep -> only 1 dragon created (idempotent)")

    # --- 4. No duplicate available egg per group (fresh group) -----------
    FRESH_CHAT = -100999888
    assert svc.spawn_wild_egg(FRESH_CHAT) is not None
    spawned = [svc.spawn_wild_egg(FRESH_CHAT) for _ in range(5)]
    assert all(e is None for e in spawned), "only one available egg per group"
    print("✓ spawning is one-per-group")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll atomicity tests passed ✅")


if __name__ == "__main__":
    main()
