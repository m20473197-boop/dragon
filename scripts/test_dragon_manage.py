"""Dragon Management System tests: multi-dragon ownership, selection buttons,
per-dragon profile/feed/rename isolation and the back button.

Run: python3 scripts/test_dragon_manage.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_manage_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)

from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.dragons import DragonService  # noqa: E402
from game.feeding import FeedingService  # noqa: E402
from handlers.dragon_manage import (  # noqa: E402
    ACTION_VIEW,
    PREFIX,
    profile_keyboard,
    profile_text,
    selection_keyboard,
    upgrade_menu_text,
)
from models.dragon import DragonRepository  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

init_db()
run_migrations()

OWNER = 1001
OTHER = 2002


def main() -> None:
    players = PlayerRepository()
    dragons = DragonRepository()
    service = DragonService(dragons)
    feeding = FeedingService(dragons=dragons, players=players)

    players.get_or_create(OWNER, "owner")
    players.get_or_create(OTHER, "other")

    # 1. A user can own multiple dragons, each with its own row/stats.
    azar = service.create_newborn(OWNER, "fire")
    yakh = service.create_newborn(OWNER, "ice")
    raad = service.create_newborn(OWNER, "green")
    service.rename(OWNER, azar.id, "آذر")
    service.rename(OWNER, yakh.id, "یخ پنجه")
    service.rename(OWNER, raad.id, "رعد")
    foreign = service.create_newborn(OTHER, "fire")
    service.rename(OTHER, foreign.id, "بیگانه")

    owned = service.list_for_owner(OWNER)
    assert len(owned) == 3
    ids = {d.id for d in owned}
    assert len({d.id for d in owned}) == 3 and foreign.id not in ids
    for d in owned:
        assert d.owner_id == OWNER
        assert all(
            getattr(d, f) is not None
            for f in ("id", "name", "dragon_type", "level", "xp", "hp", "max_hp", "power", "hunger")
        )
    print("✓ a user owns multiple dragons, each with its own id/stats")

    # 2. Selection list builds one button per dragon, carrying its own id.
    kb = selection_keyboard(list(reversed(owned)))
    labels = [b.text for row in kb.inline_keyboard for b in row]
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert len(labels) == 3
    assert any("آذر" in t for t in labels)
    assert any("یخ پنجه" in t for t in labels)
    assert any("رعد" in t for t in labels)
    assert set(datas) == {f"{PREFIX}{ACTION_VIEW}:{d.id}" for d in owned}
    print("✓ selection list shows one button per dragon name:", labels)

    # 3. Profile page contains every required field for the selected dragon.
    text = profile_text(dragons.get(azar.id))
    for token in ("نام: آذر", "نوع:", "سطح:", "تجربه:", "سلامت:", "قدرت:", "سیری:"):
        assert token in text, token
    assert "یخ پنجه" not in text and "رعد" not in text
    print("✓ profile page shows name/type/level/xp/hp/power/hunger of one dragon")

    # 4. Management buttons appear only on the profile and are bound to that id.
    pkb = profile_keyboard(azar.id)
    pdatas = [b.callback_data for row in pkb.inline_keyboard for b in row]
    plabels = [b.text for row in pkb.inline_keyboard for b in row]
    assert plabels == ["🥩 غذا دادن", "⬆️ ارتقا", "✏️ تغییر نام", "🔙 برگشت"]
    assert all(str(azar.id) in d for d in pdatas if not d.endswith("list"))
    assert f"{PREFIX}list" in pdatas  # back button returns to the list
    # No management buttons on the selection screen.
    assert not any("غذا دادن" in t or "ارتقا" in t for t in labels)
    print("✓ management buttons exist only after selection and target that dragon")

    # 5. Feeding acts on the SELECTED dragon only.
    players.add_resources(OWNER, meat=20, fish=20)
    # Newborn dragons are full; let this one get hungry so it will eat.
    import time as _t
    from game.dragons import anchor_last_fed_time
    _d = dragons.get(yakh.id)
    dragons.update_full_stats(
        _d.id, level=_d.level, xp=_d.xp, hp=_d.hp, max_hp=_d.max_hp,
        power=_d.power, hunger=50,
        last_fed_time=anchor_last_fed_time(50, _t.time()),
    )
    result = feeding.feed_unit(OWNER, yakh.id, "meat")
    assert result.success and result.dragon.id == yakh.id
    assert dragons.get(yakh.id).xp > 0
    assert dragons.get(azar.id).xp == 0 and dragons.get(raad.id).xp == 0
    print("✓ feeding from the panel affects only the selected dragon")

    # 6. A forged button cannot touch another user's dragon.
    assert dragons.get_owned(foreign.id, OWNER) is None
    stolen = feeding.feed_unit(OWNER, foreign.id, "meat")
    assert stolen.success is False and stolen.reason == "no_dragon"
    assert dragons.get(foreign.id).xp == 0
    print("✓ another user's dragon cannot be fed/modified via a forged callback")

    # 7. Rename applies to the selected dragon only (existing naming system).
    renamed = service.rename(OWNER, raad.id, "رعد بزرگ")
    assert renamed is not None and renamed.name == "رعد بزرگ"
    assert dragons.get(azar.id).name == "آذر"
    assert service.rename(OWNER, foreign.id, "هک") is None
    print("✓ rename targets the selected dragon and rejects foreign dragons")

    # 8. Upgrade view is about that dragon and lists its costs.
    up = upgrade_menu_text(dragons.get(yakh.id), 10, 10)
    assert "یخ پنجه" in up and "ارتقا" in up
    print("✓ upgrade page targets the selected dragon")

    # 9. Back button data returns to the selection list.
    back = [b for row in pkb.inline_keyboard for b in row if b.text == "🔙 برگشت"][0]
    assert back.callback_data == f"{PREFIX}list"
    print("✓ back button returns to the dragon selection list")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll dragon management tests passed ✅")


if __name__ == "__main__":
    main()
