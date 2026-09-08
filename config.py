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
COMMAND_MY_DRAGONS = "اژدهای من"
COMMAND_MY_DRAGONS_MENU = "اژدها های من"
COMMAND_NAME_DRAGON = "نام اژدها"
COMMAND_FEED = "غذا بده"
COMMAND_STORAGE = "سردخانه"
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

# --- Egg spawning in groups -------------------------------------------------
SPAWN_CHECK_INTERVAL_SECONDS: int = 180   # how often the spawner rolls per group
SPAWN_CHANCE_PER_CHECK: float = 0.40      # probability of an egg per check
SPAWN_ACTIVE_WINDOW_SECONDS: int = 2 * 24 * 3600  # only spawn in recently active groups
CLAIM_WINDOW_SECONDS: int = 15 * 60       # unclaimed eggs disappear after this
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
