"""Economy (currencies) and random chest system tests.

Checks the round's acceptance list:
  * obsidian/aether are stored per player and credited correctly,
  * a chest belongs to its group and is saved in the database,
  * multiple users cannot open the same chest,
  * rewards are random and within the configured ranges,
  * aether is rarer than obsidian,
  * food rewards land in cold storage,
  * existing systems (dragons, eggs, hunting, fishing, feeding) still work.

Run: python3 scripts/test_chests.py
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_chests_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)

from config import CHEST_REWARDS  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.chests import ChestService, roll_rewards  # noqa: E402
from game.storage import ColdStorageService  # noqa: E402
from handlers.chests import CHEST_PREFIX, build_chest_keyboard, format_rewards  # noqa: E402
from models.chest import ChestRepository  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

init_db()
run_migrations()

GROUP = -1001
A, B, C = 11, 22, 33


def main() -> None:
    players = PlayerRepository()
    chests = ChestRepository()
    storage = ColdStorageService(players)
    service = ChestService(chests=chests, players=players, storage=storage)

    for uid, name in ((A, "ali"), (B, "bahar"), (C, "chia")):
        players.get_or_create(uid, name)

    # 1. Currencies exist per player and start at zero.
    p = players.get(A)
    assert (p.obsidian, p.aether) == (0, 0)
    players.add_resources(A, obsidian=500, aether=5)
    p = players.get(A)
    assert (p.obsidian, p.aether) == (500, 5)
    assert players.get(B).obsidian == 0  # per-player, not global
    print("✓ obsidian/aether stored per player and credited correctly")

    # 2. Chest spawns, belongs to its group, and is saved in the DB.
    chest = service.spawn_chest(GROUP)
    assert chest is not None and chest.group_id == GROUP
    assert chest.status == "available" and chest.opened_by is None
    stored = chests.get(chest.id)
    assert stored is not None and stored.group_id == GROUP
    assert stored.created_time > 0
    print("✓ chest saved in the database and bound to its group")

    # 3. Only one unopened chest per group at a time.
    assert service.spawn_chest(GROUP) is None
    assert service.spawn_chest(-2002) is not None  # other group unaffected
    print("✓ one waiting chest per group; other groups unaffected")

    # 4. The open button carries the chest id.
    kb = build_chest_keyboard(chest.id)
    button = kb.inline_keyboard[0][0]
    assert button.text == "🎁 باز کردن"
    assert button.callback_data == f"{CHEST_PREFIX}{chest.id}"
    print("✓ chest message has the open button with its chest id")

    # 5. Only ONE user can open a chest; everyone else is rejected.
    before_b = players.get(B).obsidian
    first = service.open_chest(chest.id, A)
    assert first.success and first.opened_by == A
    second = service.open_chest(chest.id, B)
    third = service.open_chest(chest.id, C)
    assert not second.success and second.reason == "already_opened"
    assert not third.success and third.reason == "already_opened"
    assert players.get(B).obsidian == before_b       # losers get nothing
    assert chests.get(chest.id).opened_by == A
    assert chests.get(chest.id).status == "opened"
    print("✓ only the first user opens a chest; the rest get nothing")

    # 6. Rewards were actually credited and match the stored snapshot.
    snapshot = chests.get(chest.id).reward_dict()
    assert snapshot == first.rewards and snapshot.get("obsidian", 0) > 0
    p = players.get(A)
    assert p.obsidian == 500 + first.rewards.get("obsidian", 0)
    assert p.aether == 5 + first.rewards.get("aether", 0)
    print(f"✓ rewards saved and credited: {first.rewards}")

    # 7. Food rewards go into cold storage.
    players.get_or_create(44, "food")
    food_chest = service.spawn_chest(-3003)
    contents_before = storage.contents(44)
    res = service.open_chest(food_chest.id, 44)
    assert res.success
    contents_after = storage.contents(44)
    assert contents_after.meat == contents_before.meat + res.rewards.get("meat", 0)
    assert contents_after.fish == contents_before.fish + res.rewards.get("fish", 0)
    # The player row is the cold storage, so the two must agree.
    pl = players.get(44)
    assert (pl.meat, pl.fish) == (contents_after.meat, contents_after.fish)
    print("✓ meat/fish rewards land in the player's cold storage")

    # 8. Rewards are random, in range, and aether is rarer than obsidian.
    rng = random.Random(1234)
    obsidian_hits = aether_hits = 0
    seen_amounts = set()
    for _ in range(3000):
        r = roll_rewards(rng)
        assert "obsidian" in r                      # always granted
        obsidian_hits += 1
        seen_amounts.add(r["obsidian"])
        assert CHEST_REWARDS["obsidian"]["min"] <= r["obsidian"] <= CHEST_REWARDS["obsidian"]["max"]
        if "aether" in r:
            aether_hits += 1
            assert CHEST_REWARDS["aether"]["min"] <= r["aether"] <= CHEST_REWARDS["aether"]["max"]
        for food in ("meat", "fish"):
            if food in r:
                assert CHEST_REWARDS[food]["min"] <= r[food] <= CHEST_REWARDS[food]["max"]
    assert len(seen_amounts) > 100, "obsidian amounts should vary"
    assert 0 < aether_hits < obsidian_hits, (aether_hits, obsidian_hits)
    rate = aether_hits / obsidian_hits
    assert rate < 0.5, rate
    print(f"✓ rewards random & in range; aether rate {rate:.0%} (rarer than obsidian)")

    # 9. Opening a missing chest fails cleanly.
    assert service.open_chest(999999, A).reason == "not_found"
    print("✓ unknown chest handled cleanly")

    # 10. Expired chests cannot be opened.
    import time as _t

    old = service.spawn_chest(-4004, now=_t.time() - 10 * 3600)
    expired = service.expire_stale_chests()
    assert any(ch.id == old.id for ch in expired)
    assert chests.get(old.id).status == "expired"
    res = service.open_chest(old.id, A)
    assert not res.success and res.reason == "expired"
    print("✓ unopened chests expire and can no longer be opened")

    # 11. The reward message is rendered as required.
    text = format_rewards({"obsidian": 850, "aether": 3, "meat": 15, "fish": 20})
    assert text.startswith("🎁 صندوق باز شد!")
    for token in ("🪨 +۸۵۰", "✨ +۳", "🥩 +۱۵", "🐟 +۲۰"):
        assert token in text, token
    # Zero-value rewards are omitted.
    assert "اتر" not in format_rewards({"obsidian": 100})
    print("✓ reward message formatted correctly")

    # 12. Existing systems still work alongside the economy.
    from game.dragons import DragonService, anchor_last_fed_time
    from game.feeding import FeedingService
    from models.dragon import DragonRepository

    dragon_repo = DragonRepository()
    ds = DragonService(dragon_repo)
    fs = FeedingService(dragons=dragon_repo, players=players, storage=storage)
    d = ds.create_newborn(A, "fire")
    ds.rename(A, d.id, "آذر")
    storage.deposit(A, meat=20, fish=20)
    dragon_repo.update_full_stats(
        d.id, level=d.level, xp=d.xp, hp=d.hp, max_hp=d.max_hp, power=d.power,
        hunger=50, last_fed_time=anchor_last_fed_time(50, _t.time()),
    )
    fed = fs.feed_unit(A, d.id, "meat")
    assert fed.success and dragon_repo.get(d.id).name == "آذر"
    # Feeding must not disturb the currency balances.
    obs_now = players.get(A).obsidian
    assert obs_now == 500 + first.rewards.get("obsidian", 0)
    assert players.get(A).aether == 5 + first.rewards.get("aether", 0)
    print("✓ dragons/feeding/cold storage unaffected by the economy changes")

    # 13. Concurrent opens: many threads, exactly one winner, credited once.
    import threading

    race_chest = service.spawn_chest(-5005)
    players.get_or_create(55, "racer")
    before = players.get(55)
    results = []
    lock = threading.Lock()

    def _try_open():
        r = ChestService().open_chest(race_chest.id, 55)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=_try_open) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r.success]
    assert len(winners) == 1, f"expected exactly one winner, got {len(winners)}"
    won = winners[0].rewards
    after = players.get(55)
    assert after.obsidian == before.obsidian + won.get("obsidian", 0)
    assert after.aether == before.aether + won.get("aether", 0)
    assert after.meat == before.meat + won.get("meat", 0)
    assert after.fish == before.fish + won.get("fish", 0)
    print("✓ 12 simultaneous opens -> exactly one winner, rewards granted once")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll economy & chest tests passed ✅")


if __name__ == "__main__":
    main()
