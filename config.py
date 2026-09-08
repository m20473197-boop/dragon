"""Configuration for the Dragon bot.

Settings are read from environment variables (optionally loaded from a
``.env`` file). Keeping every tunable value here makes the game easy to
balance without touching the game logic.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv is optional; environment variables can also be set by hand.
    pass

BASE_DIR = Path(__file__).resolve().parent

# --- Telegram ---------------------------------------------------------------
BOT_TOKEN: str = os.environ.get("DRAGON_BOT_TOKEN", "").strip()

# --- Database ---------------------------------------------------------------
DB_PATH: Path = Path(os.environ.get("DRAGON_DB_PATH", str(BASE_DIR / "dragon.db")))

# --- Persian text commands (typed without a slash) --------------------------
COMMAND_HUNT = "شکار"
COMMAND_FISHING = "ماهیگیری"
COMMAND_EGGS = "تخم ها"
COMMAND_MY_DRAGONS_MENU = "اژدها"  # the only dragon/feeding entry point
COMMAND_NAME_DRAGON = "نام اژدها"
COMMAND_STORAGE = "سردخانه"
COMMAND_MARKET = "بازار"
COMMAND_BATTLE = "مبارزه"
COMMAND_ADMIN_PANEL = "پنل مدیریت"
COMMAND_ADMIN_TEST_EGG = "ساخت تخم تست"
COMMAND_ADMIN_ADD_FOOD = "اضافه غذا"

# --- Admin panel ------------------------------------------------------------
# Telegram user IDs allowed to use admin features. Set via the DRAGON_ADMIN_IDS
# environment variable as a comma-separated list, e.g. "123456789,987654321".
ADMIN_IDS: list[int] = [
    int(x)
    for x in os.environ.get("DRAGON_ADMIN_IDS", "").replace(" ", "").split(",")
    if x.lstrip("-").isdigit()
]

# Debug/testing switch. When False, testing tools are hidden and disabled
# (monitoring tools remain available to admins). Override with DRAGON_DEBUG.
DEBUG_MODE: bool = (
    os.environ.get("DRAGON_DEBUG", "true").strip().lower() in {"1", "true", "yes", "on"}
)

# Name given to admin-created test dragons (also used to identify them).
TEST_DRAGON_NAME = "تستی"

# Default name assigned to a freshly hatched dragon until the owner renames it.
DEFAULT_DRAGON_NAME = "بدون نام"

# Default stats every dragon is born with (per requirement).
DRAGON_DEFAULT_LEVEL = 1
DRAGON_DEFAULT_XP = 0
DRAGON_DEFAULT_HP = 100
DRAGON_DEFAULT_MAX_HP = 100
DRAGON_DEFAULT_POWER = 20

# --- Dragon growth ----------------------------------------------------------
# XP needed to go from `level` to `level + 1` is `level * XP_PER_LEVEL_BASE`
# (level 1 -> 2 costs 100 XP, 2 -> 3 costs 200, ...). Kept deliberately simple
# so the future combat system can grant XP against the same formula.
XP_PER_LEVEL_BASE: int = 100
LEVEL_UP_MAX_HP_BONUS: int = 20   # max HP gained per level
LEVEL_UP_POWER_BONUS: int = 5     # power gained per level

# XP awarded to the owner's dragons for a successful gathering action.
HUNT_XP: int = 25
FISH_XP: int = 15

# --- Dragon hunger ----------------------------------------------------------
DRAGON_DEFAULT_HUNGER: int = 100       # full hunger at birth / after feeding
HUNGER_DECAY_PER_HOUR: int = 20        # hunger points lost per hour
HUNGER_LOW_THRESHOLD: int = 30         # below this, power starts dropping
HUNGER_MIN_POWER_FACTOR: float = 0.5   # at 0 hunger, effective power is 50%

# --- Feeding ----------------------------------------------------------------
# Each food: how much of the resource it costs, how much hunger it restores,
# how much HP it heals, and how much XP it grants.
FOODS: dict[str, dict] = {
    "meat": {
        "name": "گوشت",
        "emoji": "🥩",
        "resource": "meat",       # player resource spent
        "cost": 3,
        "hunger": 50,
        "hp": 30,
        "xp": 20,
    },
    "fish": {
        "name": "ماهی",
        "emoji": "🐟",
        "resource": "fish",
        "cost": 5,
        "hunger": 40,
        "hp": 20,
        "xp": 15,
    },
}

# --- Feeding from the dragon profile page -----------------------------------
# The dragon page feeds in single food *units* (1 meat / 1 fish at a time),
# unlike the older bulk «غذا بده» command which is now disabled.
# Each unit restores hunger/HP and grants XP. All values are configurable.
FOOD_UNITS: dict[str, dict] = {
    "meat": {"hunger": 10, "hp": 5, "xp": 2},
    "fish": {"hunger": 8, "hp": 4, "xp": 2},
}

# Which food the page spends first when the dragon is fed (fallback follows).
FOOD_PRIORITY: tuple[str, ...] = ("meat", "fish")

# Safety cap for «🍖 سیرش کن» so one press can never consume a whole storage.
FULL_FEED_MAX_UNITS: int = 50

# --- Dragon upgrades (paid with 🪨 obsidian) --------------------------------
# Each upgrade: display text, what it improves, and its price in obsidian.
# Prices and bonuses are configurable; add new entries to extend the system.
# Food is never used for upgrading.
UPGRADES: dict[str, dict] = {
    "hp": {
        "name": "افزایش سلامت",
        "short": "HP",          # compact button label
        "emoji": "❤️",
        "stat": "max_hp",
        "amount": 20,
        "cost_obsidian": 500,
        "description": "حداکثر سلامت اژدها را بیشتر می‌کند و کامل درمانش می‌کند.",
    },
    "power": {
        "name": "افزایش قدرت",
        "short": "قدرت",        # compact button label
        "emoji": "⚔️",
        "stat": "power",
        "amount": 5,
        "cost_obsidian": 700,
        "description": "قدرت پایه‌ی اژدها را بیشتر می‌کند.",
    },
    "level": {
        "name": "افزایش سطح",
        "short": "سطح",         # compact button label
        "emoji": "⭐",
        "stat": "level",
        "amount": 1,
        "cost_obsidian": 1000,
        "description": "یک سطح به اژدها اضافه می‌کند (سلامت و قدرت هم رشد می‌کنند).",
    },
}

# Naming flow.
DRAGON_NAME_MAX_LENGTH: int = 32
NAME_PROMPT_TIMEOUT_SECONDS: int = 120  # how long the bot waits for a name

# --- Gathering balance ------------------------------------------------------
HUNT_COOLDOWN_SECONDS: int = 5 * 60       # time between hunts (spam protection)
FISHING_COOLDOWN_SECONDS: int = 10 * 60   # time between fishing trips

# Huntable prey: key -> Persian name, emoji, spawn weight and meat range.
# The amount of meat is rolled per animal from (meat_min, meat_max).
HUNT_PREY: dict[str, dict] = {
    "rabbit":  {"name": "خرگوش",  "emoji": "🐇", "weight": 55, "meat_min": 1, "meat_max": 3},
    "deer":    {"name": "گوزن",   "emoji": "🦌", "weight": 25, "meat_min": 4, "meat_max": 7},
    "gazelle": {"name": "غزال",   "emoji": "🦌", "weight": 20, "meat_min": 5, "meat_max": 9},
}

# Fishing reward: random number of fish caught per trip.
FISH_FISH_MIN: int = 10
FISH_FISH_MAX: int = 20

# Chance to personally *find* an egg while gathering (it is immediately
# incubated by the finder, same as a claimed group egg).
HUNT_EGG_CHANCE: float = 0.15
FISHING_EGG_CHANCE: float = 0.10

# --- Currencies -------------------------------------------------------------
# Two player currencies, stored on the players table. There is no shop or
# spending system yet — these are storage + receiving only.
CURRENCIES: dict[str, dict] = {
    "obsidian": {"name": "ابسیدین", "emoji": "🪨", "column": "obsidian"},
    "aether":   {"name": "اتر",     "emoji": "✨", "column": "aether"},
}

# --- Random chests ----------------------------------------------------------
# A chest may appear in an active group; the first user to press the button
# opens it and receives the rewards.
CHEST_CHECK_INTERVAL_SECONDS: int = 300    # how often the spawner rolls per group
CHEST_CHANCE_PER_CHECK: float = 0.25       # probability of a chest per check
CHEST_ACTIVE_WINDOW_SECONDS: int = 2 * 24 * 3600  # only in recently active groups
CHEST_SWEEP_INTERVAL_SECONDS: int = 60     # how often expired chests are cleaned

# --- Temporary messages (Version 5) -----------------------------------------
# Chests and eggs are temporary: if nobody claims them, their message is
# DELETED and the reward is removed from play. After a successful claim the
# result message is also deleted, so old messages never pile up in a group.
#
# All three timers are stored as absolute deadlines in the database, so they
# survive a bot restart, and every group is swept independently.
CHEST_EXPIRE_TIME: int = int(
    os.environ.get("DRAGON_CHEST_EXPIRE_TIME", 30 * 60)
)   # unopened chest: delete the message and drop the chest
EGG_EXPIRE_TIME: int = int(
    os.environ.get("DRAGON_EGG_EXPIRE_TIME", 30 * 60)
)   # uncollected egg: delete the message and drop the egg
MESSAGE_DELETE_TIME: int = int(
    os.environ.get("DRAGON_MESSAGE_DELETE_TIME", 5 * 60)
)   # after a successful open/collect, delete the result message
CLEANUP_SWEEP_INTERVAL_SECONDS: int = 30   # how often deadlines are checked

# The window in which a chest can still be opened is exactly its lifetime, so
# the button never outlives the message (kept under the historical name that
# the chest service and tests already use).
CHEST_OPEN_WINDOW_SECONDS: int = CHEST_EXPIRE_TIME

# Chest reward table. Every chest always grants obsidian; the other rewards
# are rolled independently with their own chance, so aether stays rare.
CHEST_REWARDS: dict[str, dict] = {
    "obsidian": {"chance": 1.00, "min": 100, "max": 2000},
    "aether":   {"chance": 0.15, "min": 1,   "max": 10},
    "meat":     {"chance": 0.60, "min": 5,   "max": 30},
    "fish":     {"chance": 0.60, "min": 5,   "max": 30},
}

# --- Market (بازار) ---------------------------------------------------------
# Everything purchasable, priced in 🪨 obsidian only. Amounts and prices are
# configuration, so the market can grow without touching the code.
# 'special' is intentionally empty: reserved for future items.
MARKET_ITEMS: dict[str, dict] = {
    "food": {
        "meat": {
            "name": "گوشت", "emoji": "🥩", "price": 50,
            "amount": 10, "kind": "food", "resource": "meat",
        },
        "fish": {
            "name": "ماهی", "emoji": "🐟", "price": 40,
            "amount": 10, "kind": "food", "resource": "fish",
        },
    },
    "eggs": {
        "common": {
            "name": "تخم معمولی", "emoji": "🥚", "price": 800,
            "amount": 1, "kind": "egg", "egg_type": "common",
        },
    },
    # Reserved for future content — no items yet, on purpose.
    "special": {},
}

# 'short' is the compact button label; 'name' is the page title.
MARKET_CATEGORIES: dict[str, dict] = {
    "food":    {"name": "غذا", "short": "غذا", "emoji": "🥩"},
    "eggs":    {"name": "تخم اژدها", "short": "تخم", "emoji": "🥚"},
    "special": {"name": "آیتم‌های ویژه", "short": "ویژه", "emoji": "✨"},
}

# --- Egg spawning in groups -------------------------------------------------
SPAWN_CHECK_INTERVAL_SECONDS: int = 180   # how often the spawner rolls per group
SPAWN_CHANCE_PER_CHECK: float = 0.40      # probability of an egg per check

# Minimum time between two eggs in the SAME group. The spawner still rolls on
# its check interval, but a group that spawned an egg is on cooldown until
# this many seconds have passed, so at most one egg appears per interval.
# Each group has its own timer (stored in the database, so it survives a
# restart). Override with the DRAGON_EGG_SPAWN_INTERVAL environment variable:
# production 7200 (2 hours), testing e.g. 60.
EGG_SPAWN_INTERVAL: int = int(
    os.environ.get("DRAGON_EGG_SPAWN_INTERVAL", 2 * 60 * 60)
)
SPAWN_ACTIVE_WINDOW_SECONDS: int = 2 * 24 * 3600  # only spawn in recently active groups
# An egg can be collected for exactly as long as its message lives, so the
# button never outlives the message (see EGG_EXPIRE_TIME above).
CLAIM_WINDOW_SECONDS: int = EGG_EXPIRE_TIME
HATCH_SWEEP_INTERVAL_SECONDS: int = 30    # how often eggs are hatched/expired

# --- Egg types --------------------------------------------------------------
# Each type: display name, emoji, spawn weight, incubation time and the pool
# of dragons (with weights) that can hatch from it.
EGG_TYPES: dict[str, dict] = {
    "common": {
        "name": "تخم اژدهای معمولی",
        "emoji": "🥚",
        "weight": 70,
        "hatch_seconds": 15 * 60,
        "dragons": {"green": 60, "fire": 30, "ice": 10},
    },
    "rare": {
        "name": "تخم اژدهای کمیاب",
        "emoji": "💎",
        "weight": 25,
        "hatch_seconds": 45 * 60,
        "dragons": {"fire": 35, "ice": 35, "golden": 25, "shadow": 5},
    },
    "legendary": {
        "name": "تخم اژدهای افسانه‌ای",
        "emoji": "👑",
        "weight": 5,
        "hatch_seconds": 2 * 60 * 60,
        "dragons": {"golden": 60, "shadow": 40},
    },
}

# --- Dragon types -----------------------------------------------------------
DRAGON_TYPES: dict[str, dict] = {
    "green":  {"name": "اژدهای سبز",   "emoji": "🐲"},
    "fire":   {"name": "اژدهای آتشین", "emoji": "🔥"},
    "ice":    {"name": "اژدهای یخی",   "emoji": "❄️"},
    "golden": {"name": "اژدهای طلایی", "emoji": "✨"},
    "shadow": {"name": "اژدهای سایه",  "emoji": "🌑"},
}


def require_token() -> str:
    """Return the bot token or raise a helpful error."""
    if not BOT_TOKEN:
        raise RuntimeError(
            "Bot token is missing. Set the DRAGON_BOT_TOKEN environment "
            "variable (copy .env.example to .env and fill it in)."
        )
    return BOT_TOKEN


# --- Combat (Version 4: basic PvE) ------------------------------------------
# Enemies a dragon can meet with the «مبارزه» command. One is picked at random
# (weighted). Everything here is configuration, so new enemies can be added
# without touching the combat code. No PvP, bosses, equipment or skills.
ENEMIES: dict[str, dict] = {
    "wolf": {
        "name": "گرگ وحشی",
        "emoji": "🐺",
        "max_hp": 80,
        "attack_power": 10,
        "reward_min": 60,
        "reward_max": 140,
        "xp_min": 15,
        "xp_max": 25,
        "weight": 45,
    },
    "forest_monster": {
        "name": "هیولای جنگل",
        "emoji": "👹",
        "max_hp": 120,
        "attack_power": 16,
        "reward_min": 120,
        "reward_max": 260,
        "xp_min": 25,
        "xp_max": 40,
        "weight": 35,
    },
    "giant_scorpion": {
        "name": "عقرب غول پیکر",
        "emoji": "🦂",
        "max_hp": 100,
        "attack_power": 22,
        "reward_min": 150,
        "reward_max": 320,
        "xp_min": 30,
        "xp_max": 50,
        "weight": 20,
    },
}

# Damage rolling. The dragon hits for its (hunger-adjusted) power plus a random
# bonus; the enemy hits for its attack power with a small random spread.
BATTLE_DAMAGE_BONUS_MIN: int = 0
BATTLE_DAMAGE_BONUS_MAX: int = 10
BATTLE_ENEMY_DAMAGE_SPREAD: int = 3     # enemy damage is power ± this
BATTLE_MIN_DAMAGE: int = 1              # a hit always does at least this much

# The dragon never dies. When its HP would drop to or below this value it is
# "weakened": HP is clamped here and the battle is lost.
BATTLE_DRAGON_MIN_HP: int = 1
# A dragon at or below this HP is too weak to start a new battle and must rest.
BATTLE_MIN_HP_TO_FIGHT: int = 10

# Rare bonus currency on a win.
BATTLE_AETHER_CHANCE: float = 0.12
BATTLE_AETHER_MIN: int = 1
BATTLE_AETHER_MAX: int = 3

# Abandoned battles (nobody pressed a button) are reclaimed after this, so a
# player is never locked out of «مبارزه» by a forgotten fight.
BATTLE_STALE_SECONDS: int = 30 * 60
