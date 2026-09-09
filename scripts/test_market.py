"""Market system tests (tool-upgrades-only market).

Checks the round's requirements:
  * «بازار» shows ONLY the two tool categories,
  * food and dragon eggs can no longer be bought (no items, no buy handler),
  * the cold storage and the egg system are untouched and still work,
  * players keep the food/eggs they already own,
  * tool upgrades still work and are the market's only purchase,
  * only obsidian is spent (aether untouched).

Run: python3 scripts/test_market.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp_db = Path(tempfile.gettempdir()) / "dragon_market_test.db"
_tmp_db.unlink(missing_ok=True)
os.environ["DRAGON_DB_PATH"] = str(_tmp_db)
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")

from config import MARKET_CATEGORIES, MARKET_ITEMS  # noqa: E402
from database.init_db import init_db  # noqa: E402
from database.migrate import run_migrations  # noqa: E402
from game import market as market_module  # noqa: E402
from game.eggs import EggService  # noqa: E402
from game.market import MarketService  # noqa: E402
from game.storage import ColdStorageService  # noqa: E402
from game.tools import ROD, WEAPON, ToolService  # noqa: E402
from handlers import market as mk  # noqa: E402
from handlers.market import (  # noqa: E402
    PREFIX,
    categories_keyboard,
    market_text,
)
from models.egg import EggRepository  # noqa: E402
from models.player import PlayerRepository  # noqa: E402

init_db()
run_migrations()

BUYER = 900
POOR = 901
GROUP = -700


class FakeQuery:
    def __init__(self, user, data):
        self.from_user = user
        self.data = data
        self.answers = []
        self.edits = []
        self.message = type("M", (), {"message_id": 1, "chat_id": GROUP})()

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None, **kw):
        self.edits.append((text, reply_markup))


class FakeUser:
    def __init__(self, uid):
        self.id = uid
        self.username = f"u{uid}"
        self.full_name = f"u{uid}"
        self.is_bot = False


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def main() -> None:
    players = PlayerRepository()
    storage = ColdStorageService(players)
    eggs = EggRepository()
    egg_service = EggService()
    tools = ToolService(players=players)
    market = MarketService(players=players)

    players.get_or_create(BUYER, "buyer")
    players.get_or_create(POOR, "poor")

    # 1. The market shows ONLY the two tool categories.
    btns = labels(categories_keyboard())
    assert btns == ["🎣 ابزار ماهیگیری", "🏹 ابزار شکار", "🔙"], btns
    print("✓ market shows only the two tool categories")

    assert set(MARKET_CATEGORIES) == {"rod", "hunt"}, MARKET_CATEGORIES
    assert set(MARKET_ITEMS) == {"rod", "hunt"}, MARKET_ITEMS
    print("✓ food / eggs / special categories are gone")

    # 2. Nothing is purchasable as an "item" any more.
    all_items = [k for cat in MARKET_ITEMS.values() for k in cat]
    assert all_items == [], all_items
    for gone in ("food", "eggs", "special"):
        assert gone not in MARKET_ITEMS, gone
        assert gone not in MARKET_CATEGORIES, gone
    print("✓ no buyable items remain (no meat, fish or eggs)")

    # 3. The buying API and its UI helpers are removed outright.
    for attr in ("buy", "_buy_food", "_buy_egg", "get_item", "list_category"):
        assert not hasattr(market, attr) and not hasattr(market_module, attr), attr
    for attr in ("category_keyboard", "category_text", "purchase_text", "ACTION_BUY"):
        assert not hasattr(mk, attr), attr
    print("✓ buy handlers and item screens removed")

    # 4. The market title is unchanged and short.
    text = market_text(1234)
    assert text.startswith("🏪 بازار"), text
    assert "۱۲۳۴" in text, text
    assert len([ln for ln in text.split("\n") if ln.strip()]) <= 3, text
    print("✓ «🏪 بازار» screen is short and shows the balance")

    # 5. A stale «buy food» callback is ignored safely (old buttons in chat).
    user = FakeUser(BUYER)
    ctx = type("C", (), {"bot_data": {
        "player_repo": players, "market_service": market, "tool_service": tools,
    }})()
    before = (players.get(BUYER).obsidian, storage.contents(BUYER).meat)
    for stale in (f"{PREFIX}buy:food:meat", f"{PREFIX}cat:food", f"{PREFIX}cat:eggs",
                  f"{PREFIX}buy:eggs:common"):
        q = FakeQuery(user, stale)
        run(mk.market_callback(type("U", (), {"callback_query": q})(), ctx))
        assert q.edits == [], (stale, q.edits)
    after = (players.get(BUYER).obsidian, storage.contents(BUYER).meat)
    assert before == after, (before, after)
    print("✓ stale buy/category buttons do nothing (no food or eggs granted)")

    # 6. Existing inventory is preserved — the cold storage still works.
    storage.deposit(BUYER, meat=25, fish=40)
    contents = storage.contents(BUYER)
    assert (contents.meat, contents.fish) == (25, 40), contents
    assert storage.consume(BUYER, "meat", 5) is True
    assert storage.contents(BUYER).meat == 20, storage.contents(BUYER).meat
    print("✓ cold storage untouched: deposits and spending still work")

    # 7. The egg system still works (spawn -> claim), just not via the shop.
    egg = egg_service.spawn_wild_egg(GROUP)
    assert egg is not None
    claimed, _ = egg_service.claim_egg(egg.id, BUYER)
    assert claimed is not None and claimed.owner_id == BUYER
    assert len(eggs.list_active_by_owner(BUYER)) == 1
    print("✓ egg system untouched: spawn and claim still work")

    # 8. Tool upgrades are still buyable and remain the market's only purchase.
    players.add_resources(BUYER, obsidian=2000)
    obs_before = players.get(BUYER).obsidian
    aether_before = players.get(BUYER).aether
    q = FakeQuery(user, f"{PREFIX}toolup:rod")
    run(mk.market_callback(type("U", (), {"callback_query": q})(), ctx))
    assert q.edits and "🎉 ارتقا موفق!" in q.edits[0][0], q.edits
    assert tools.level(BUYER, ROD) == 2, tools.level(BUYER, ROD)
    assert players.get(BUYER).obsidian == obs_before - 2000
    assert players.get(BUYER).aether == aether_before, "aether must not be spent"
    print("✓ tool upgrades still work and only spend obsidian")

    # 9. Both tool screens render.
    for category, needle in (("rod", "قلاب فعلی"), ("hunt", "ابزار شکار")):
        q = FakeQuery(user, f"{PREFIX}cat:{category}")
        run(mk.market_callback(type("U", (), {"callback_query": q})(), ctx))
        body, markup = q.edits[0]
        assert needle in body, (category, body)
        assert "⬆️ ارتقا" in labels(markup), labels(markup)
    print("✓ both tool screens render with an upgrade button")

    # 10. A poor player cannot upgrade, and loses nothing.
    poor_user = FakeUser(POOR)
    poor_before = players.get(POOR).obsidian
    q = FakeQuery(poor_user, f"{PREFIX}toolup:hunt")
    run(mk.market_callback(type("U", (), {"callback_query": q})(), ctx))
    assert any(a and "ابسیدین کافی نیست" in a for a in q.answers), q.answers
    assert players.get(POOR).obsidian == poor_before
    assert tools.level(POOR, WEAPON) == 1
    print("✓ upgrades refused without enough obsidian (nothing spent)")

    # 11. Unknown categories are ignored.
    q = FakeQuery(user, f"{PREFIX}cat:chests")
    run(mk.market_callback(type("U", (), {"callback_query": q})(), ctx))
    assert q.edits == [], q.edits
    print("✓ unknown categories ignored")

    print("\nAll market tests passed ✅")


if __name__ == "__main__":
    main()
