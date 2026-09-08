"""Market system tests.

Checks the round's requirements:
  * «بازار» shows the three categories plus back,
  * food is bought with obsidian and lands in cold storage,
  * eggs are bought with obsidian and use the EXISTING egg system,
  * purchases are refused without enough obsidian (never negative),
  * special items category exists but is empty,
  * only obsidian is spent (aether untouched), no chests are sold,
  * everything is persisted, and other systems keep working.

Run: python3 scripts/test_market.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_market_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)

from config import MARKET_CATEGORIES, MARKET_ITEMS  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game.market import MarketService  # noqa: E402
from game.storage import ColdStorageService  # noqa: E402
from handlers.market import (  # noqa: E402
    PREFIX,
    categories_keyboard,
    category_keyboard,
    category_text,
    market_text,
    purchase_text,
)
from models.egg import EggRepository  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

init_db()
run_migrations()

BUYER = 900
POOR = 901
GROUP = -700


def main() -> None:
    players = PlayerRepository()
    storage = ColdStorageService(players)
    eggs = EggRepository()
    market = MarketService(players=players, storage=storage)

    players.get_or_create(BUYER, "buyer")
    players.get_or_create(POOR, "poor")

    # 1. The market screen offers the three categories and a back button.
    labels = [b.text for row in categories_keyboard().inline_keyboard for b in row]
    assert labels == ["🥩 غذا", "🥚 تخم اژدها", "✨ آیتم‌های ویژه", "🔙 برگشت"], labels
    assert "🏪 بازار اژدها" in market_text(0)
    assert set(MARKET_CATEGORIES) == {"food", "eggs", "special"}
    print("✓ «بازار» shows the three categories + back button")

    # 2. Food shop lists meat and fish with prices and buy buttons.
    food_btns = [b for row in category_keyboard("food").inline_keyboard for b in row]
    assert len(food_btns) == 3           # meat, fish, back
    assert all("خرید" in b.text for b in food_btns[:2])
    assert food_btns[0].callback_data == f"{PREFIX}buy:food:meat"
    text = category_text("food", 100)
    assert "گوشت" in text and "ماهی" in text and "ابسیدین" in text
    print("✓ food shop lists 🥩/🐟 with obsidian prices and buy buttons")

    # 3. Buying food: obsidian removed, food into cold storage.
    players.add_resources(BUYER, obsidian=1000)
    meat_item = MARKET_ITEMS["food"]["meat"]
    before = storage.contents(BUYER)
    res = market.buy(BUYER, "food", "meat")
    assert res.success, res.reason
    after = storage.contents(BUYER)
    assert after.meat == before.meat + meat_item["amount"]
    assert after.fish == before.fish                       # only what was bought
    assert players.get(BUYER).obsidian == 1000 - meat_item["price"]
    assert res.balance == players.get(BUYER).obsidian
    assert "✅ خرید انجام شد!" in purchase_text(res)
    print(f"✓ bought {meat_item['amount']} meat for {meat_item['price']} obsidian -> cold storage")

    # 4. Fish works the same and spends only obsidian (aether untouched).
    players.add_resources(BUYER, aether=7)
    aether_before = players.get(BUYER).aether
    obs_before = players.get(BUYER).obsidian
    fish_item = MARKET_ITEMS["food"]["fish"]
    res = market.buy(BUYER, "food", "fish")
    assert res.success
    assert storage.contents(BUYER).fish == fish_item["amount"]
    assert players.get(BUYER).obsidian == obs_before - fish_item["price"]
    assert players.get(BUYER).aether == aether_before      # aether never spent
    print("✓ fish purchase charges obsidian only; aether is never spent")

    # 5. Egg shop sells a common egg through the EXISTING egg system.
    egg_item = MARKET_ITEMS["eggs"]["common"]
    obs_before = players.get(BUYER).obsidian
    eggs_before = players.get(BUYER).eggs
    res = market.buy(BUYER, "eggs", "common", chat_id=GROUP)
    assert res.success and res.egg_id is not None
    egg = eggs.get(res.egg_id)
    assert egg is not None
    assert egg.owner_id == BUYER
    assert egg.egg_type == "common"
    assert egg.status == "incubating"          # normal pipeline, will hatch
    assert egg.hatch_time and egg.hatch_time > egg.spawn_time
    assert egg.chat_id == GROUP
    assert players.get(BUYER).eggs == eggs_before + 1      # counter kept in sync
    assert players.get(BUYER).obsidian == obs_before - egg_item["price"]
    print("✓ bought a common egg: owned, incubating, uses the existing egg system")

    # 6. The purchased egg hatches through the normal hatch process.
    from game.eggs import EggService

    service = EggService(eggs=eggs, players=players)
    from database.connection import get_db

    with get_db() as conn:                     # make it due in the past
        conn.execute("UPDATE eggs SET hatch_time = 1.0 WHERE id = ?", (res.egg_id,))
    events = service.process_hatchings()
    assert any(e.egg.id == res.egg_id for e in events), "purchased egg must hatch normally"
    hatched = [e for e in events if e.egg.id == res.egg_id][0]
    assert hatched.dragon.owner_id == BUYER
    print("✓ the purchased egg hatches into a dragon like any other egg")

    # 7. Not enough obsidian -> refused, nothing changes, never negative.
    poor_before = players.get(POOR)
    assert poor_before.obsidian == 0
    res = market.buy(POOR, "food", "meat")
    assert not res.success and res.reason == "not_enough"
    assert res.missing == MARKET_ITEMS["food"]["meat"]["price"]
    poor_after = players.get(POOR)
    assert poor_after.obsidian == 0 and poor_after.obsidian >= 0
    assert (poor_after.meat, poor_after.fish) == (poor_before.meat, poor_before.fish)
    # Partially-funded purchase is refused too.
    players.add_resources(POOR, obsidian=MARKET_ITEMS["eggs"]["common"]["price"] - 1)
    res = market.buy(POOR, "eggs", "common")
    assert not res.success and res.reason == "not_enough" and res.missing == 1
    assert players.get(POOR).obsidian >= 0
    assert players.get(POOR).eggs == 0
    print("✓ purchases without enough obsidian are refused; balance never negative")

    # 8. Repeated buying drains the balance but can never overdraw it.
    players.get_or_create(902, "spender")
    players.add_resources(902, obsidian=125)   # enough for 2 meat (50 each)
    bought = 0
    for _ in range(10):
        if market.buy(902, "food", "meat").success:
            bought += 1
    assert bought == 2, bought
    assert players.get(902).obsidian == 25
    assert storage.contents(902).meat == 2 * MARKET_ITEMS["food"]["meat"]["amount"]
    print("✓ repeated purchases stop exactly when obsidian runs out")

    # 9. Special items category exists but is empty (reserved for the future).
    assert MARKET_ITEMS["special"] == {}
    special_btns = [b for row in category_keyboard("special").inline_keyboard for b in row]
    assert len(special_btns) == 1 and special_btns[0].text == "🔙 برگشت"
    assert "هنوز آیتمی اینجا نیست" in category_text("special", 0)
    print("✓ special items category is present but empty")

    # 10. Nothing sells chests and no new currency exists.
    all_items = [k for cat in MARKET_ITEMS.values() for k in cat]
    assert not any("chest" in k or "صندوق" in k for k in all_items)
    from config import CURRENCIES
    assert set(CURRENCIES) == {"obsidian", "aether"}
    assert market.buy(BUYER, "chests", "any").reason == "unknown_item"
    assert market.buy(BUYER, "food", "dragon").reason == "unknown_item"
    print("✓ no chest shop, no new currencies, unknown items rejected")

    # 11. Other systems still work (hunting deposit, feeding, chest opening).
    from game.chests import ChestService

    storage.deposit(BUYER, meat=5, fish=5)     # as hunting/fishing would
    chest_service = ChestService(players=players, storage=storage)
    chest = chest_service.spawn_chest(-808)
    opened = chest_service.open_chest(chest.id, BUYER)
    assert opened.success
    assert players.get(BUYER).obsidian >= 0
    print("✓ hunting deposits, chests and currencies still work alongside the market")

    # 12. Concurrent double-taps can never overspend the same obsidian.
    import threading

    players.get_or_create(903, "tapper")
    price = MARKET_ITEMS["food"]["meat"]["price"]
    players.add_resources(903, obsidian=price)   # exactly one purchase worth
    results = []
    lock = threading.Lock()

    def _tap():
        r = MarketService().buy(903, "food", "meat")
        with lock:
            results.append(r)

    threads = [threading.Thread(target=_tap) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    wins = [r for r in results if r.success]
    assert len(wins) == 1, f"expected exactly one purchase, got {len(wins)}"
    final = players.get(903)
    assert final.obsidian == 0 and final.obsidian >= 0
    assert final.meat == MARKET_ITEMS["food"]["meat"]["amount"]
    print("✓ 10 simultaneous taps -> exactly one purchase, no overspend")

    _tmp_db.unlink(missing_ok=True)
    print("\nAll market tests passed ✅")


if __name__ == "__main__":
    main()
