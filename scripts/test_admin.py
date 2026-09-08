"""Admin panel tests (no Telegram needed): permissions, test tools, stats,
user info, hatch override and safe reset. Uses a throwaway SQLite file.

Run: DRAGON_ADMIN_IDS=1 DRAGON_DEBUG=true python3 scripts/test_admin.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Configure before importing project modules.
_tmp_db = Path(tempfile.gettempdir()) / "dragon_admin_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)
os.environ["DRAGON_ADMIN_IDS"] = "1"
os.environ["DRAGON_DEBUG"] = "true"

from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from admin.permissions import can_use_test_tools, debug_enabled, is_admin  # noqa: E402
from admin.service import AdminService  # noqa: E402
from game import hatch_override  # noqa: E402
from game.eggs import EggService  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

init_db()
run_migrations()


def main() -> None:
    players = PlayerRepository()
    admin = AdminService()
    players.get_or_create(1, "admin")
    players.get_or_create(2, "normal_user")

    # 1. Permission gating.
    assert is_admin(1) and not is_admin(2) and not is_admin(None)
    assert can_use_test_tools(1) and not can_use_test_tools(2)
    assert debug_enabled() is True
    print("✓ admin allow-list + debug gating works")

    # 2. Add food goes into the target's cold storage.
    assert admin.add_food(2, "meat", 100)
    assert admin.add_food(2, "fish", 7)
    p2 = players.get(2)
    assert (p2.meat, p2.fish) == (100, 7)
    assert admin.add_food(999, "meat", 5) is False  # unknown user
    print("✓ admin can add meat/fish; unknown user rejected")

    # 3. Test dragon: named تستی, defaults, marked test, counter updated.
    d = admin.create_test_dragon(2)
    assert d is not None and d.name == "تستی"
    assert (d.level, d.xp, d.hp, d.max_hp, d.power) == (1, 0, 100, 100, 20)
    assert d.is_test == 1
    assert players.get(2).dragons == 1
    assert admin.create_test_dragon(999) is None
    print("✓ test dragon created with defaults + is_test; counter consistent")

    # 4. Hatch override affects new eggs' hatch time; production config untouched.
    from config import EGG_TYPES
    production_common = EGG_TYPES["common"]["hatch_seconds"]
    hatch_override.set_hatch_seconds(10)
    assert EggService.hatch_seconds("common") == 10
    assert EGG_TYPES["common"]["hatch_seconds"] == production_common  # config unchanged
    hatch_override.set_hatch_seconds(None)
    assert EggService.hatch_seconds("common") == production_common
    print("✓ hatch override works without changing production config")

    # 5. Test egg is created, marked, and uses the real claim/hatch pipeline.
    hatch_override.set_hatch_seconds(10)
    egg = admin.spawn_test_egg(-500)
    assert egg is not None and egg.is_test == 1 and egg.status == "available"
    # It can be claimed like a real egg.
    claimed, _ = admin.egg_service.claim_egg(egg.id, 2)
    assert claimed is not None and claimed.owner_id == 2
    print("✓ test egg spawns, is marked, and claims via the normal pipeline")
    hatch_override.set_hatch_seconds(None)

    # 6. Stats include action counters and totals.
    # Simulate a couple of gathering counts.
    with __import__("database.connection", fromlist=["get_db"]).get_db() as conn:
        conn.execute("UPDATE players SET hunt_count = 3, fishing_count = 2 WHERE user_id = 2")
    from models.chat import ChatRepository
    ChatRepository().touch(-500, "Test Group")
    stats = admin.game_stats()
    assert stats["users"] == 2
    assert stats["dragons"] == 1
    assert stats["groups"] >= 1
    assert stats["hunts"] == 3 and stats["fishing"] == 2
    assert stats["eggs"] >= 1
    print("✓ game stats aggregate users/eggs/dragons/groups/hunts/fishing")

    # 7. User info.
    info = admin.user_info(2)
    assert info.user_id == 2 and info.meat == 100 and info.fish == 7
    assert info.dragons == 1 and len(info.dragons_list) == 1
    assert admin.user_info(999) is None
    print("✓ user info returns resources, counters and dragon stats")

    # 8. Reset deletes ONLY test data; real data survives.
    # Create a "real" (non-test) dragon + egg for user 1 to prove safety.
    real = admin.dragons.create(
        owner_id=1, dragon_type="green", from_egg_id=None, name="real",
        level=1, xp=0, hp=100, max_hp=100, power=20, hunger=100, is_test=0,
    )
    players.add_resources(1, dragons=1)
    admin.egg_service.create_found_egg(-500, 1)  # real egg
    before_users = players.count_all()
    result = admin.reset_test_data()
    assert result["dragons"] == 1  # only the تستی dragon removed
    assert result["eggs"] >= 1     # the test egg removed
    # Real dragon/player/resources intact.
    assert admin.dragons.get(real.id) is not None
    assert players.get(1).dragons == 1
    assert players.get(2).meat == 100 and players.get(2).fish == 7
    assert players.count_all() == before_users == 2
    # Test dragon owner counter was adjusted down.
    assert players.get(2).dragons == 0
    print("✓ reset removes only test data; real users/resources/dragons preserved")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll admin tests passed ✅")


if __name__ == "__main__":
    main()
