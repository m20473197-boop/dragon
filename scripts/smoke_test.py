"""Smoke test for the database and game logic (no Telegram needed).

Uses a throwaway SQLite file so the real database is never touched::

    python3 scripts/smoke_test.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

# Make the project root importable when run as `python scripts/smoke_test.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Point the DB at a temp file BEFORE importing project modules that read config.
_tmp_db = Path(tempfile.gettempdir()) / "dragon_smoke_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)

from config import CLAIM_WINDOW_SECONDS as CLAIM_WINDOW  # noqa: E402
from database.connection import get_db  # noqa: E402
from database.init_db import init_db  # noqa: E402
from config import HUNT_PREY  # noqa: E402
from game import actions  # noqa: E402
from game.eggs import EggService  # noqa: E402
from models.chat import ChatRepository  # noqa: E402
from models.egg import (  # noqa: E402
    EggRepository,
    STATUS_AVAILABLE,
    STATUS_EXPIRED,
    STATUS_HATCHED,
    STATUS_INCUBATING,
)
from models.player import PlayerRepository  # noqa: E402
from utils.text import format_remaining, normalize_command, to_fa  # noqa: E402


def main() -> None:
    init_db()
    players = PlayerRepository()
    chats = ChatRepository()
    eggs = EggRepository()
    svc = EggService()

    # 1. New player is created automatically on first action.
    player, created = players.get_or_create(1001, "ali_test")
    assert created and player.meat == 0, "new player should start empty"
    print("✓ player created")

    # 2. Hunt catches a random prey with its meat range, and sets the cooldown.
    r = actions.hunt(players, player)
    assert r.success, r
    assert r.prey_key in HUNT_PREY, r.prey_key
    prey = HUNT_PREY[r.prey_key]
    # Meat now comes from the player's 🏹 weapon level, not the prey entry.
    from game.tools import WEAPON, allowed_prey, reward_range
    w_min, w_max = reward_range(WEAPON, 1)
    assert w_min <= r.meat_gained <= w_max, (r.prey_key, r.meat_gained)
    assert r.prey_key in allowed_prey(1), r.prey_key
    assert players.get(1001).meat == r.meat_gained  # persisted
    r2 = actions.hunt(players, player)
    assert not r2.success and r2.cooldown_remaining > 290, r2
    print(f"✓ hunt: caught {r.prey_key} ({prey['name']}), +{r.meat_gained} meat; cooldown works")

    # 3. Fishing yields 10-20 fish and sets its own cooldown.
    f = actions.fish(players, player)
    # Fish now comes from the player's 🎣 rod level.
    from game.tools import ROD as _ROD, reward_range as _rr
    _fmin, _fmax = _rr(_ROD, 1)
    assert f.success and _fmin <= f.fish_gained <= _fmax, f
    assert players.get(1001).fish == f.fish_gained
    f2 = actions.fish(players, player)
    assert not f2.success and f2.cooldown_remaining > 590, f2
    print(f"✓ fishing: +{f.fish_gained} fish (10-20); cooldown works")

    # --- Egg spawning system -------------------------------------------------
    CHAT = -1001234567890

    # 4. Active chats are tracked and returned by the spawner window.
    chats.touch(CHAT, "گروه تست")
    active = chats.active_chats(within_seconds=3600)
    assert any(c.chat_id == CHAT for c in active), "chat should be active"
    print("✓ chat tracking works")

    # 5. A wild egg spawns with required fields.
    t0 = time.time()
    egg = svc.spawn_wild_egg(CHAT, now=t0)
    assert egg is not None
    assert egg.status == STATUS_AVAILABLE and egg.owner_id is None
    assert egg.spawn_time == t0 and egg.hatch_time is None
    assert egg.egg_type in {"common", "rare", "legendary"}
    print(f"✓ wild egg #{egg.id} spawned (type={egg.egg_type})")

    # 6. Only one unclaimed egg per group at a time.
    assert svc.spawn_wild_egg(CHAT, now=t0) is None
    print("✓ no duplicate unclaimed egg in a group")

    # 7. Claiming is race-safe: only the first clicker wins.
    players.get_or_create(2002, "sara")
    players.get_or_create(3003, "reza")
    claimed_by_winner, current_after_first = svc.claim_egg(egg.id, 2002, now=t0 + 5)
    claimed_by_loser, current_after_second = svc.claim_egg(egg.id, 3003, now=t0 + 6)

    assert claimed_by_winner is not None and claimed_by_winner.owner_id == 2002
    assert current_after_first.status == STATUS_INCUBATING
    assert current_after_first.hatch_time is not None
    assert claimed_by_loser is None                      # loser wins nothing
    assert current_after_second.owner_id == 2002         # owner stays winner
    assert players.get(2002).eggs == 1                   # winner's egg counter up
    assert players.get(3003).eggs == 0
    print("✓ only one user can claim each egg (race-safe)")

    # 8. Found eggs (hunt/fishing) are immediately owned + incubating.
    found = svc.create_found_egg(CHAT, 1001, now=t0)
    assert found.status == STATUS_INCUBATING and found.owner_id == 1001
    assert found.hatch_time == t0 + svc.hatch_seconds(found.egg_type)
    assert players.get(1001).eggs == 1
    active_eggs = svc.eggs.list_active_by_owner(1001)
    assert len(active_eggs) == 1 and active_eggs[0].id == found.id
    print("✓ found egg is owned, incubating, and listed in «تخم ها»")

    # 9. Automatic hatching: due eggs become a random dragon with default stats.
    # Force both incubating eggs' hatch_time into the past.
    with get_db() as conn:
        conn.execute("UPDATE eggs SET hatch_time = ? WHERE status = 'incubating'", (t0 - 1,))
    events = svc.process_hatchings(now=t0)
    assert len(events) == 2, f"expected 2 hatchings, got {len(events)}"
    for ev in events:
        assert ev.dragon.dragon_type in {
            "green", "fire", "ice", "golden", "shadow"
        }, ev.dragon.dragon_type
        assert ev.dragon.owner_id in {1001, 2002}
        # Dragon data system: full stats present with default values.
        assert ev.dragon.id is not None
        assert ev.dragon.name == "بدون نام", ev.dragon.name
        assert (ev.dragon.level, ev.dragon.xp) == (1, 0)
        assert (ev.dragon.hp, ev.dragon.max_hp, ev.dragon.power) == (100, 100, 20)
    print("✓ hatched dragons carry full default stats (name/level/xp/hp/power)")
    # Counters: eggs gone, dragons gained.
    assert players.get(1001).eggs == 0 and players.get(1001).dragons == 1
    assert players.get(2002).eggs == 0 and players.get(2002).dragons == 1
    assert all(e.status == STATUS_HATCHED for e in eggs.list_by_owner(1001))
    assert all(e.status == STATUS_HATCHED for e in eggs.list_by_owner(2002))
    print("✓ due eggs hatch automatically into random dragons")

    # 10. Unclaimed eggs expire after the claim window.
    # No egg is currently waiting (egg #1 was claimed in step 7), so spawn one.
    stale = svc.spawn_wild_egg(CHAT, now=t0)
    assert stale is not None and stale.status == STATUS_AVAILABLE and stale.owner_id is None
    # Right away it is not stale yet.
    assert svc.expire_stale_eggs(now=t0 + CLAIM_WINDOW - 1) == []
    assert svc.eggs.get(stale.id).status == STATUS_AVAILABLE
    # Past the claim window it expires.
    expired = svc.expire_stale_eggs(now=t0 + CLAIM_WINDOW + 1)
    assert any(e.id == stale.id and e.status == STATUS_EXPIRED for e in expired)
    assert svc.eggs.get(stale.id).status == STATUS_EXPIRED
    print("✓ unclaimed eggs expire after the claim window")

    # 11. Persian helpers.
    assert to_fa(123) == "۱۲۳"
    assert "دقیقه" in format_remaining(150)
    assert normalize_command("  تخم‌ها  ") == "تخم ها"
    assert normalize_command("شکار") == "شکار"
    print("✓ Persian text helpers work")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll smoke tests passed ✅")


if __name__ == "__main__":
    main()
