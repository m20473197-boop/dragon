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

from config import FOODS, HUNGER_DECAY_PER_HOUR  # noqa: E402
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

    # 4. Feeding meat consumes 3 meat, heals, grants XP and restores hunger.
    players.add_resources(1, meat=6, fish=7)
    # Make the dragon hurt and hungry.
    with get_db() as conn:
        conn.execute(
            "UPDATE dragons SET hp = 50, last_fed_time = ? WHERE id = ?",
            (now - 6 * HOUR, d.id),
        )
    hungry_d = fs.dragons.get(d.id)
    assert current_hunger(hungry_d, now) == 0

    r = fs.feed(1, "meat")
    assert r.success, r.reason
    after = fs.dragons.get(d.id)
    assert players.get(1).meat == 6 - FOODS["meat"]["cost"] == 3  # 3 spent
    assert after.hp == 80                      # 50 + 30 heal
    assert after.xp == FOODS["meat"]["xp"] == 20
    assert r.hp_healed == 30
    assert r.hunger_after == 0 + FOODS["meat"]["hunger"] == 50
    print("✓ meat: -3 meat, +HP, +XP, +hunger")

    # 5. Not-enough-food is rejected and changes nothing.
    r2 = fs.feed(1, "meat")
    assert r2.success
    assert players.get(1).meat == 0           # now out of meat
    pre_state = fs.dragons.get(d.id)
    pre_meat = players.get(1).meat
    r3 = fs.feed(1, "meat")
    assert not r3.success and r3.reason == "not_enough"
    # The rejected feed leaves both resources and dragon untouched.
    assert players.get(1).meat == pre_meat == 0
    post = fs.dragons.get(d.id)
    assert (post.xp, post.hp, post.hunger, post.level) == (
        pre_state.xp, pre_state.hp, pre_state.hunger, pre_state.level
    )
    print("✓ insufficient food is rejected (no resources consumed)")

    # 6. Fish costs 5 fish. XP carries over from the two meat feeds (20+20=40).
    xp_before_fish = fs.dragons.get(d.id).xp
    assert players.get(1).fish == 7
    r4 = fs.feed(1, "fish")
    assert r4.success and r4.reason == ""
    assert players.get(1).fish == 7 - FOODS["fish"]["cost"] == 2
    after_fish = fs.dragons.get(d.id)
    assert after_fish.xp == xp_before_fish + FOODS["fish"]["xp"]
    print("✓ fish: -5 fish, +HP, +XP")

    # 7. Feeding can trigger a level-up (enough XP) and fully restores HP.
    # Give lots of fish and keep feeding the fish path (small XP but cheap).
    players.add_resources(1, meat=0, fish=200)
    # Damage the dragon first; a level-up should heal to max.
    with get_db() as conn:
        conn.execute("UPDATE dragons SET hp = 5 WHERE id = ?", (d.id,))
    saw_level = False
    for _ in range(40):
        res = fs.feed(1, "fish")
        if not res.success:
            break
        if res.levels_gained:
            saw_level = True
    assert saw_level, "feeding XP should cause at least one level-up"
    final = fs.dragons.get(d.id)
    assert final.level >= 2
    assert final.hp == final.max_hp           # level-up fully heals
    assert final.max_hp == 100 + (final.level - 1) * 20
    assert final.power == 20 + (final.level - 1) * 5
    print(f"✓ feeding XP caused level-ups -> L{final.level}, HP healed to max {final.max_hp}")

    # 8. A player with no dragon gets a clear failure.
    players.get_or_create(2, "nobody")
    assert fs.feed(2, "meat").reason == "no_dragon"
    print("✓ feeding without a dragon returns no_dragon")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll feeding tests passed ✅")


if __name__ == "__main__":
    main()
