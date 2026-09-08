"""Feeding & hunger system tests (no Telegram needed).

Uses a throwaway SQLite file::

    python3 scripts/test_feeding.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_feeding_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)

from config import FOOD_UNITS, HUNGER_DECAY_PER_HOUR  # noqa: E402
from database.connection import get_db  # noqa: E402
from database.init_db import init_db  # noqa: E402
from game.dragons import (  # noqa: E402
    DragonService,
    current_hunger,
    effective_power,
)
from game.feeding import FeedingService  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

HOUR = 3600


def main() -> None:
    init_db()
    players = PlayerRepository()
    ds = DragonService()
    fs = FeedingService()
    players.get_or_create(1, "ali")

    # 1. A newborn dragon is full (100) and at full power.
    d = ds.create_newborn(1, "fire")
    now = time.time()
    assert current_hunger(d, now) == 100
    assert effective_power(d.power, 100) == d.power
    print("✓ newborn hunger 100, full power")

    # 2. Hunger decays 20/hour and floors at 0.
    d.last_fed_time = now - 3.5 * HOUR
    assert current_hunger(d, now) == round(100 - 3.5 * HUNGER_DECAY_PER_HOUR) == 30
    d.last_fed_time = now - 6 * HOUR
    assert current_hunger(d, now) == 0
    print("✓ hunger decays over time and floors at 0")

    # 3. Low hunger reduces effective power (full at >=30, 50% at 0).
    assert effective_power(20, 100) == 20
    assert effective_power(20, 30) == 20
    assert effective_power(20, 0) == 10
    assert 10 < effective_power(20, 15) < 20
    print("✓ hunger lowers power below threshold (100% full, 50% at 0)")

    # 4. One unit of meat: -1 meat, heals, grants XP and restores hunger.
    players.add_resources(1, meat=6, fish=7)
    # Make the dragon hurt and starving.
    with get_db() as conn:
        conn.execute(
            "UPDATE dragons SET hp = 50, last_fed_time = ? WHERE id = ?",
            (now - 6 * HOUR, d.id),
        )
    assert current_hunger(fs.dragons.get(d.id), now) == 0

    unit = FOOD_UNITS["meat"]
    r = fs.feed_unit(1, d.id, "meat")
    assert r.success, r.reason
    after = fs.dragons.get(d.id)
    assert players.get(1).meat == 5                 # exactly one unit spent
    assert after.hp == 50 + unit["hp"]
    assert after.xp == unit["xp"]
    assert r.hp_healed == unit["hp"]
    assert r.hunger_after == unit["hunger"]
    # The derived hunger (shown on the dragon page) must match what the feed
    # reported — this locks the last_fed_time anchoring fix.
    assert current_hunger(after, now) == r.hunger_after, (
        current_hunger(after, now),
        r.hunger_after,
    )
    print("✓ one meat unit: -1 meat, +HP, +XP, +hunger; derived hunger consistent")

    # 5. An empty storage is rejected and changes nothing.
    players.spend_resource(1, "meat", 5)
    players.spend_resource(1, "fish", 7)
    assert (players.get(1).meat, players.get(1).fish) == (0, 0)
    pre = fs.dragons.get(d.id)
    r3 = fs.feed_unit(1, d.id, "meat")
    assert not r3.success and r3.reason == "no_food"
    post = fs.dragons.get(d.id)
    assert (post.xp, post.hp, post.level) == (pre.xp, pre.hp, pre.level)
    assert players.get(1).meat == 0
    print("✓ feeding with an empty cold storage is rejected (nothing consumed)")

    # 6. Fish works the same way and spends fish only.
    players.add_resources(1, fish=7)
    xp_before = fs.dragons.get(d.id).xp
    r4 = fs.feed_unit(1, d.id, "fish")
    assert r4.success and r4.reason == ""
    assert players.get(1).fish == 6 and players.get(1).meat == 0
    assert fs.dragons.get(d.id).xp == xp_before + FOOD_UNITS["fish"]["xp"]
    print("✓ one fish unit: -1 fish, +HP, +XP")

    # 7. Feeding XP can trigger a level-up, which fully restores HP.
    players.add_resources(1, fish=500)
    with get_db() as conn:
        conn.execute("UPDATE dragons SET hp = 5 WHERE id = ?", (d.id,))
    saw_level = False
    for _ in range(400):
        # Keep it hungry so it will keep eating.
        with get_db() as conn:
            conn.execute(
                "UPDATE dragons SET last_fed_time = ? WHERE id = ?",
                (time.time() - 6 * HOUR, d.id),
            )
        res = fs.feed_unit(1, d.id, "fish")
        if not res.success:
            break
        if res.levels_gained:
            saw_level = True
            break
    assert saw_level, "feeding XP should cause at least one level-up"
    final = fs.dragons.get(d.id)
    assert final.level >= 2
    assert final.hp == final.max_hp           # level-up fully heals
    assert final.max_hp == 100 + (final.level - 1) * 20
    assert final.power == 20 + (final.level - 1) * 5
    print(f"✓ feeding XP caused a level-up -> L{final.level}, healed to {final.max_hp}")

    # 8. A dragon that is not yours cannot be fed.
    players.get_or_create(2, "nobody")
    assert fs.feed_unit(2, d.id, "meat").reason == "no_dragon"
    assert fs.feed_unit(2, 999999, "meat").reason == "no_dragon"
    print("✓ feeding a dragon you do not own returns no_dragon")

    # 9. A full dragon refuses food.
    fs.feed_until_full(1, d.id)
    assert fs.feed_unit(1, d.id, "fish").reason == "full"
    print("✓ a full dragon cannot be fed")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll feeding tests passed \u2705")


if __name__ == "__main__":
    main()
