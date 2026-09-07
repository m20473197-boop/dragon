"""Growth-system tests (no Telegram needed): naming, XP curve and level-ups.

Uses a throwaway SQLite file::

    python3 scripts/test_growth.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_growth_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)

from config import LEVEL_UP_MAX_HP_BONUS, LEVEL_UP_POWER_BONUS  # noqa: E402
from database.init_db import init_db  # noqa: E402
from game.dragons import DragonService, xp_required_for_level  # noqa: E402
from models.player import PlayerRepository  # noqa: E402


def main() -> None:
    init_db()
    players = PlayerRepository()
    ds = DragonService()
    players.get_or_create(1, "ali")

    # 1. Required XP curve: level -> next level costs level * 100.
    assert [xp_required_for_level(l) for l in (1, 2, 3)] == [100, 200, 300]
    print("✓ required-XP formula: 100, 200, 300 for levels 1,2,3")

    # 2. Newborn defaults.
    d = ds.create_newborn(1, "fire")
    assert (d.level, d.xp, d.hp, d.max_hp, d.power) == (1, 0, 100, 100, 20)
    assert d.name == "بدون نام"
    print("✓ newborn defaults")

    # 3. XP below threshold does not level.
    r = ds.add_xp(d.id, 99)
    assert not r.leveled_up and r.dragon.level == 1 and r.dragon.xp == 99
    print("✓ partial XP stored, no level-up")

    # 4. Crossing threshold: level up, +max HP, +power, HP restored.
    from database.connection import get_db

    with get_db() as conn:
        conn.execute("UPDATE dragons SET hp = 10 WHERE id = ?", (d.id,))
    r = ds.add_xp(d.id, 1)  # 99 + 1 = 100 -> L2
    assert r.leveled_up and r.dragon.level == 2
    assert r.dragon.max_hp == 100 + LEVEL_UP_MAX_HP_BONUS
    assert r.dragon.power == 20 + LEVEL_UP_POWER_BONUS
    assert r.dragon.hp == r.dragon.max_hp  # healed fully
    assert r.dragon.xp == 0
    print("✓ level-up raises max HP (+20) and power (+5) and restores HP")

    # 5. One big XP grant can cross several levels.
    r = ds.add_xp(d.id, 500)  # L2 -> pay 200 (L3), pay 300 (L4)
    assert r.dragon.level == 4 and len(r.level_ups) == 2
    assert r.dragon.max_hp == 100 + 3 * LEVEL_UP_MAX_HP_BONUS
    assert r.dragon.power == 20 + 3 * LEVEL_UP_POWER_BONUS
    print("✓ multi level-up in a single grant")

    # 6. Naming + ownership protection.
    renamed = ds.rename(1, d.id, "رخش")
    assert renamed is not None and renamed.name == "رخش"
    assert ds.rename(999, d.id, "hacker") is None  # not the owner
    assert ds.dragons.get(d.id).name == "رخش"
    print("✓ rename persists and rejects non-owners")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll growth tests passed ✅")


if __name__ == "__main__":
    main()
