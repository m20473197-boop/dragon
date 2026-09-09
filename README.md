# 🐉 Dragon — Telegram Group Bot Game

An RPG-style game bot that lives inside Telegram **groups**. Dragon eggs spawn
randomly in the chat — players race to tap the button to claim them, then wait
while the egg incubates until it hatches into a random dragon. Players can also
hunt and fish for food, and may find eggs that way too. Commands are plain
**Persian words with no slash** (`/`).

Built with **Python**, **python-telegram-bot v21** (Job Queue), and **SQLite**.
No mini app, no web interface — just messages and buttons.

## How the egg system works

1. **Spawning** — every few minutes the spawner visits each *active* group and
   may drop an egg. The group gets:

   > 🥚 یک تخم اژدهای ناشناخته پیدا شد!

   with an inline button **«🥚 نگهداری از تخم»**.
2. **Claiming** — the first member to tap wins. Claiming is an atomic
   `UPDATE ... WHERE owner_id IS NULL`, so even at the same instant **only one
   user** gets each egg. Losers get a "someone was faster" alert; the button is
   removed once claimed.
3. **Incubation** — each egg has a type (معمولی / کمیاب / افسانه‌ای) with its own
   hatch duration. The owner sees the type and a live countdown with `تخم ها`.
4. **Hatching** — a sweep job automatically hatches every egg whose time is up,
   creates a **random dragon** (weighted by egg rarity), and announces it in the
   group, tagging the owner.
5. **Expiry** — unclaimed eggs disappear after the claim window (button removed).

Every egg row stores: **egg type, owner, spawn time, hatch time, status**
(`available → incubating → hatched`, or `expired`).

## Game commands

Send these as normal messages in the group (no `/`):

| Command    | Meaning          | Effect                                                        |
|------------|------------------|--------------------------------------------------------------|
| `شکار`      | Hunt             | Catch a random animal (🐇 خرگوش / 🦌 گوزن / 🦌 غزال) for 1–9 🥩 meat. 15% chance to **find an egg** (auto-owned). 5 min cooldown (spam-protected). |
| `ماهیگیری`  | Fishing          | Catch 10–20 🐟 fish. 10% chance to **find an egg** (auto-owned). 10 min cooldown. |
| `تخم ها`    | My eggs / inventory | Lists your incubating eggs: type + time until hatching, plus dragons/meat/fish. |
| `اژدها های من` | Dragon management | Selection-first panel: one inline button per dragon, then that dragon's profile with 🥩 غذا دادن / ⬆️ ارتقا / ✏️ تغییر نام / 🔙 برگشت. **All feeding happens here.** |
| `نام اژدها` | Name dragon      | The bot asks for a name; your next message names your most recent dragon. Sending a game command cancels it. |
| `سردخانه`   | Cold storage     | Shows your ❄️ سردخانه (cold storage): stored 🥩 گوشت and 🐟 ماهی. |

Plus one **slash** command:

| Command  | Meaning | Effect |
|----------|---------|--------|
| `/arena` | 🏟️ Arena PvP | Opens the arena: find an opponent, leaderboard, your dragon's arena profile. See [Arena PvP](#-arena-pvp-version-7). |

### Cold storage (سردخانه)

Every player has a basic **❄️ سردخانه** (cold storage) that holds their food —
🥩 meat and 🐟 fish. It is deliberately simple: **no levels, no upgrades and no
capacity limits**.

- Hunting deposits meat **directly into cold storage**; fishing deposits fish
  **directly into cold storage**.
- Feeding (from a dragon's page) consumes food **from cold storage**.

The amounts live on the player record (`players.meat` / `players.fish`, also
shown by `تخم ها`/`اژدها های من`); the named `game/storage.py::ColdStorageService`
is the single place that reads and spends them, shared by the feed system.

> ❄️ سردخانه من
>
> 🥩 گوشت: ۹
>
> 🐟 ماهی: ۱۳

## 🛠 Admin panel (development / testing / monitoring)

The admin panel is a separate, gated module (`admin/`) — normal users cannot
reach it. Access is based on a Telegram user-ID allow-list, and testing tools
additionally require debug mode.

- **Admins:** set `DRAGON_ADMIN_IDS` (comma-separated IDs) in `.env`. Only those
  IDs can use `پنل مدیریت`. Every admin callback re-checks permissions server-side.
- **Debug mode:** `DRAGON_DEBUG=true` enables the test tools; `false` hides and
  disables them (the monitoring buttons remain available).

Admin command (no slash): **`پنل مدیریت`** opens the panel:

| Button | Action |
|--------|--------|
| 🥚 ساخت تخم تست | Spawns a real, claimable test egg in the group (marked `is_test`). |
| 🐉 ساخت اژدهای تست | Creates a «تستی» level-1 dragon (HP 100 / power 20 / XP 0) for the replied-to user (or the admin). |
| 🍖 اضافه کردن غذا | Adds meat/fish to a user's cold storage. Multiline shortcut: `اضافه غذا` / `گوشت\|ماهی` / `100` (reply to a user to target them). |
| ⏩ تغییر زمان تخم | Testing-only hatch override: 10s / 1min / 5min / reset (production values never change). |
| 📊 آمار بازی | Total users, eggs, dragons, groups, hunts, fishing trips. |
| 👤 اطلاعات کاربر | ID, username, eggs, dragons, meat, fish and per-dragon stats (reply or send numeric ID). |
| 🗑 پاک کردن اطلاعات تست | Asks for confirmation, then deletes **only** `is_test` eggs/dragons — real data is never touched. |

Test rows are flagged with an additive `is_test` column (migrated in place);
reset deletes only those rows and corrects counters. Action statistics use
`players.hunt_count` / `fishing_count`, bumped atomically with each gather.

### Hunger & feeding

- **Hunger:** every dragon has a `hunger` percentage (stored; **100 = full** at
  birth). It decays **20 points per hour**. At or above 30 the dragon fights at
  full power; below 30 its **effective power** scales down to 50% at 0 hunger
  (`game/dragons.py::effective_power`, used by the arena).
- **Feeding:** happens **only** on a dragon's own page (`اژدها های من` → select
  a dragon → `🥩 غذا دادن`); there is no feeding command. Food is spent one unit
  at a time, atomically (guarded `UPDATE`), so rapid taps can never over-spend.
  Feeding XP can trigger level-ups (+max HP/power and full heal). Logic lives in
  `game/feeding.py` (`FeedingService.feed_unit` / `feed_until_full`).

### Dragon growth

- **Naming:** send `نام اژدها`, then reply with a name (1–32 characters). The
  name is saved on the dragon (ownership-checked).
- **XP & leveling:** successful `شکار` (+25 XP) and `ماهیگیری` (+15 XP) award XP
  to your newest dragon. The XP needed to advance from level *L* to *L+1* is
  `L × 100` (1→2 costs 100, 2→3 costs 200, …). On level-up the dragon gains
  **+20 max HP**, **+5 power** and is **fully healed**:

  > 🎉 اژدهای «رخش» Level Up شد!
  > ⭐ Level: ۲
  > ❤️ +۲۰ Max HP
  > 🔥 +۵ Power

  The growth engine lives in `game/dragons.py` (`DragonService.add_xp`); a
  single XP grant can cross multiple levels and is applied atomically. The
  arena awards XP through this same `add_xp` entry point.

### Dragon data system

When an egg hatches, a new dragon row is created for the owner. Its **element**
and **rarity** are rolled from the egg's own tables (see
[Egg rarity & dragon origin](#-egg-rarity--dragon-origin-version-8)):

- **name:** `بدون نام` (unnamed — ready for a future rename feature)
- **element:** fixed by the egg, or random (e.g. 🔥 اژدهای آتشین)
- **rarity:** ⚪ / 🟢 / 🔵 / 🟣 / 🟡, which scales the starting stats
- **level:** 1 · **xp:** 0 · **hp / max_hp / power:** base 100 / 100 / 20,
  multiplied by the rarity (a 🔵 حماسی newborn starts at 125 / 125 / 25)

The `dragons` table stores `id, owner_id, name, type, level, xp, hp, max_hp,
power, rarity` (plus `from_egg_id`, `born_at`). On startup `database/migrate.py`
adds any missing columns to older databases, so existing installs upgrade in
place. Dragon creation/reading lives in `game/dragons.py` (`DragonService`);
PvP lives in `game/arena.py`.

Both gathering actions are cooldown-protected (the bot remembers and saves the
last hunt/fishing time per user and rejects spam with a live wait timer).

Example hunt response:

> 🏹 شکار موفق!
>
> 🦌 یک گوزن شکار کردی
>
> 🥩 ۵ گوشت دریافت کردی

Example fishing response:

> 🎣 ماهیگیری موفق!
>
> 🐟 ۱۵ ماهی گرفتی

Also: `/start` and `/help` show the welcome message.

Players are registered automatically the first time they tap or type a command —
their Telegram user ID is the primary key.

## Egg & dragon types

| Egg type | Spawn | Incubation | Element | Rarity chances |
|----------|------:|-----------:|---------|----------------|
| 🥚 تخم اژدهای معمولی | 55 | 15 min | 🎲 random | ⚪85 🟢13 🔵2 |
| 💎 تخم اژدهای کمیاب | 20 | 45 min | 🎲 random | ⚪70 🟢22 🔵7 🟣1 |
| 👑 تخم اژدهای افسانه‌ای | 4 | 2 h | 🎲 random | ⚪50 🟢28 🔵15 🟣6 🟡1 |
| 🥚 تخم کهن | 12 | 20 min | 🎲 random | ⚪75 🟢20 🔵5 |
| 🔥 تخم شعله جاودان | 5 | 1 h | 🔥 آتش | ⚪60 🟢25 🔵12 🟣3 |
| ❄️ تخم کریستال یخی | 5 | 1 h | ❄️ یخ | ⚪60 🟢25 🔵12 🟣3 |
| ⚡ تخم طوفان آسمانی | 4 | 75 min | ⚡ صاعقه | ⚪55 🟢27 🔵14 🟣4 |
| 🌑 تخم سایه باستانی | 3 | 90 min | 🌑 سایه | ⚪40 🟢30 🔵20 🟣8 🟡2 |
| 🌌 تخم اژدهای نخستین | **never** | 3 h | 🌌 نخستین | 🔵45 🟣40 🟡15 |

Dragon elements: 🐲 طبیعت · 🔥 آتش · ❄️ یخ · ✨ نور · 🌑 سایه · ⚡ صاعقه ·
🌌 نخستین. All numbers, weights, timings and names live in `config.py`.

## ⚠️ Important: enable group messages in BotFather

Bots in groups only receive plain text if **Group Privacy** is off:

1. Open [@BotFather](https://t.me/BotFather)
2. `/mybots` → your bot → **Bot Settings** → **Group Privacy** → **Turn off**
3. Remove and re-add the bot to your group.

The bot does **not** need admin rights.

## Setup

```bash
cd dragon_bot
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # includes the [job-queue] extra (APScheduler)

cp .env.example .env               # paste your bot token from @BotFather

python bot.py
```

The SQLite database (`dragon.db`) and all tables are created automatically.
Override its path with `DRAGON_DB_PATH`.

> **Secrets:** `.env` holds your real token and is git-ignored — only
> `.env.example` is committed. Never commit `.env`, and never put a token in
> source, CI config or a test.

### Continuous integration

`.github/workflows/main.yml` runs on every push to `main`: pyflakes lint, an
import check of `bot.py`, then all 19 test suites against a throwaway database
with a **dummy** token supplied via workflow `env`.

CI must never run `python bot.py`: that starts long-polling, never exits, and a
second polling client fights the live bot for `getUpdates` (see the Conflict
section). The import check verifies wiring without touching the network.

## Project structure

```
dragon_bot/
├── bot.py                  # Entry point: init DB, build app, start polling
├── config.py               # Token, DB path, commands, balance, egg/dragon types
├── database/
│   ├── connection.py       # SQLite connection (WAL, busy timeout) + db_scope/get_db
│   ├── schema.sql          # players, chats, eggs, dragons tables
│   └── init_db.py          # Creates tables/triggers on startup
├── models/                 # Data-access layer (the only place with SQL)
│   ├── player.py           # PlayerRepository incl. atomic apply_gather / cooldown
│   ├── chat.py             # ChatRepository (active groups)
│   ├── egg.py              # EggRepository: atomic claim, spawn, idempotent hatch
│   ├── dragon.py           # DragonRepository
│   └── arena.py            # ArenaBattleRepository (PvP duel history)
├── game/                   # Rules only — no Telegram imports
│   ├── actions.py          # hunt(), fish() (atomic reward + cooldown)
│   ├── arena.py            # ArenaService: matchmaking, duel simulation, leagues
│   ├── rarity.py           # Egg rarity/element rolling + stat scaling (V8)
│   └── eggs.py             # EggService: spawn, claim, found eggs, hatch, expire
├── handlers/               # Telegram only
│   ├── __init__.py         # Router + register_all() (handlers, error handler, jobs)
│   ├── common.py           # /start, /help
│   ├── tracking.py         # Records group activity for the spawner (best-effort)
│   ├── spawn.py            # Spawn message, inline button, claim callback
│   ├── jobs.py             # spawn_tick() + hatch_sweep() scheduled jobs
│   ├── errors.py           # Global error handler
│   ├── hunt.py             # شکار
│   ├── fishing.py          # ماهیگیری
│   ├── arena.py            # /arena (PvP menu, battle, ranking)
│   └── eggs.py             # تخم ها
├── utils/
│   ├── text.py             # Persian digits, cooldown text, command normalization
│   └── rng.py              # weighted_choice() helper
└── scripts/
    ├── smoke_test.py       # Tests DB + game logic (full egg lifecycle)
    ├── test_arena.py       # Arena PvP: matchmaking, balance, limits, migration
    ├── test_rarity.py      # Egg rarity/origin: chances, scaling, compatibility
    └── test_atomicity.py   # Concurrency tests: no duplicate rewards/dragons
```

### Layers

- **handlers/** — Telegram only: turn updates/jobs into service calls and format
  Persian replies.
- **game/** — The rules. `EggService` owns the whole egg lifecycle; pure Python.
- **models/** — Data access. Each repository owns one table's SQL.
- **database/** — Connection/schema plumbing.

## Adding a new feature

- **New command (e.g. `بازار`):** add the word to `config.py`, write a rule in
  `game/`, write an async handler in `handlers/`, register it in `COMMAND_MAP`
  in `handlers/__init__.py`.
- **New egg/dragon type or balance tweak:** edit the `EGG_TYPES` / `DRAGON_TYPES`
  dicts in `config.py` — weights and hatch times flow everywhere automatically.
- **New stat:** add the column to `database/schema.sql` (safe on fresh installs;
  for an existing DB run an `ALTER TABLE ... ADD COLUMN`), add it to the model
  dataclass/`from_row`, and extend the repository.

## Stability & data-integrity notes

- **Duplicate-action protection.** Hunting/fishing claim their cooldown and
  grant rewards in a *single atomic SQL update* (`PlayerRepository.apply_gather`),
  so double-tapping or rapid messages can never grant twice.
- **Race-safe eggs.** Claiming is a guarded `UPDATE ... WHERE status='available'
  AND owner_id IS NULL`; spawning only inserts when the group has no waiting egg
  (one statement); hatching only flips an egg that is still `incubating`, so a
  repeated sweep can never create two dragons from one egg.
- **Transactions.** Every multi-step operation (found egg, claim, hatch) runs in
  one DB transaction (`db_scope` / `get_db`) — a failure mid-way rolls back.
- **SQLite tuning.** Connections use WAL journaling + a busy timeout so
  concurrent writes wait instead of raising "database is locked".
- **Error handling.** A global error handler logs unexpected failures and gives
  users a friendly message; jobs isolate each chat/egg so one failure never
  aborts a sweep; callback queries are always answered (no hanging spinner).
- **Group safety.** Chat tracking is best-effort (never breaks commands),
  spawning only targets active groups, and messages use escaped user mentions.

## Tests

```bash
python3 scripts/smoke_test.py        # full feature lifecycle
python3 scripts/test_atomicity.py    # concurrency: no duplicate rewards/dragons

# everything (what CI runs):
for s in scripts/test_*.py scripts/smoke_test.py; do python3 "$s" || break; done
```

There are 23 suites; `test_admin.py` needs `DRAGON_ADMIN_IDS=1 DRAGON_DEBUG=true`.
Runs against a throwaway DB. The smoke test covers player creation,
hunting/fishing, cooldowns, chat tracking, spawning, claiming, found eggs,
hatching and expiry; the atomicity test runs **concurrent** hunts and claims in
threads and verifies exactly one reward / one winner, plus idempotent hatching.

## 🐉 Dragon Management System

A user can own any number of dragons; each row in `dragons` keeps its own
`dragon_id`, `owner_id`, `name`, `type`, `level`, `xp`, `hp`, `max_hp`,
`power` and `hunger` (the existing table — nothing was replaced).

`اژدها های من` does **not** dump every dragon into one message. It replies:

> 🐉 اژدهای خود را انتخاب کنید:

with one inline button per dragon (`🔥 آذر`, `❄️ یخ پنجه`, `⚡ رعد`). Choosing
one **edits** the same message into that dragon's profile page (name, type,
level, XP, HP, power, hunger) with the management buttons below it:

| Button | Behaviour |
|--------|-----------|
| 🥩 غذا دادن | Opens the feeding menu for **this** dragon (see below). |
| ⬆️ ارتقا | Upgrade menu for this dragon: ❤️ HP, 🔥 power, ⭐ level, paid with stored food. |
| ✏️ تغییر نام | Opens the existing naming prompt bound to **this** dragon id. |
| 🔙 برگشت | Edits the message back to the dragon selection list. |

**Isolation:** the selected `dragon_id` travels in the callback data and every
action re-loads it with `get_owned(dragon_id, owner_id)`, so an action can only
ever touch a dragon the presser owns — no accidental edits to another dragon,
and forged callbacks for someone else's dragon are rejected. Management buttons
only exist on a profile page, never on the selection list.

Implemented in `handlers/dragon_manage.py`; feeding goes through
`FeedingService.feed_unit()` / `feed_until_full()`, which always take the
selected `dragon_id`. Tests: `scripts/test_dragon_manage.py`.

## 🥩 Feeding system (dragon page only)

The `غذا بده` and `اژدهای من` commands have been **removed completely** — the
commands, their handlers, their modules and the old `feed:` inline buttons are
all gone, so neither word does anything now. Feeding is reached only through `اژدها های من` → select a dragon → `🥩 غذا دادن`,
which shows `🥩 غذا دادن به (نام اژدها)` plus the current hunger and cold-storage
contents, with three buttons:

| Button | Behaviour |
|--------|-----------|
| 🥩 یک غذا بده | Consumes **one** food unit from cold storage for the selected dragon: hunger up, HP healed if hurt, XP added. Reports `70% → 80%`. |
| 🍖 سیرش کن | Computes exactly how much the dragon still needs and consumes **only that much** — never more, and it stops at 100%. If storage runs out it feeds what it can and says so. |
| 🔙 برگشت | Back to the dragon profile. |

If the dragon is already full, both actions answer `🐉 اژدهای تو سیر است!` and
consume nothing. Per-unit values live in `config.FOOD_UNITS`
(meat +10 hunger/+5 HP/+2 XP, fish +8/+4/+2), the spend order in
`FOOD_PRIORITY`, and a `FULL_FEED_MAX_UNITS` safety cap bounds one press.

**Cold storage (❄️ سردخانه)** is unchanged and remains the single food store:
hunting deposits 🥩 meat, fishing deposits 🐟 fish, and every feed/upgrade
spends from it with guarded atomic updates.

## ⬆️ Dragon upgrades

`⬆️ ارتقا` on a dragon's page upgrades **only that dragon** and is paid with
**🪨 obsidian** — food is never spent on upgrades. Pressing it shows
`⬆️ ارتقای اژدها` with one button per upgrade (price included) plus `🔙 برگشت`.
Defined in `config.UPGRADES`, so prices, bonuses and new upgrade types are
configuration changes only:

| Upgrade | Effect | Default price |
|---------|--------|---------------|
| ❤️ افزایش سلامت | +20 max HP (and a full heal) | 🪨 500 |
| 🔥 افزایش قدرت | +5 power | 🪨 700 |
| ⭐ افزایش سطح | +1 level (with the usual per-level HP/power gains) | 🪨 1000 |

Implemented in `game/upgrades.py`. Payment uses the guarded `spend_currency`
UPDATE, so obsidian can never go negative and ten simultaneous taps apply
exactly one upgrade; ownership is enforced on every apply, and unknown
upgrades/foreign dragons are rejected without charging. Tests:
`scripts/test_upgrades.py`.

## 🎯 Active dragon

`players.active_dragon_id` (additive column, migrated in place) stores **one**
active dragon per user. Selecting a dragon from the list makes it active — it is
marked with ✅ in the selection list — and the first dragon to hatch becomes
active automatically. Setting it is guarded by an ownership check, and the
pointer is cleared if that dragon is removed. Nothing else depends on it yet;
it is in place for future features.

Tests: `scripts/test_feeding_v3.py` (feeding, upgrades, active dragon).

## 💰 Economy: currencies

Every player has two currencies, stored on the `players` table (additive
columns, migrated in place):

| Currency | Field | Notes |
|----------|-------|-------|
| 🪨 ابسیدین (obsidian) | `obsidian` | Main currency |
| ✨ اتر (aether) | `aether` | Rare currency, kept for future features |

There is **no shop, spending or aether usage** yet — only storage and
receiving. Balances are visible at the bottom of `سردخانه`:

> ❄️ سردخانه من
>
> 🥩 گوشت: ۹ · 🐟 ماهی: ۱۳
>
> 💰 دارایی — 🪨 ابسیدین: ۵۰۰ · ✨ اتر: ۵

## 🎁 Random chest system

A `chest_tick` job rolls for a mystery chest in each active group (every
5 minutes, 25% chance, at most one waiting chest per group). The bot posts:

> 🎁 یک صندوق مرموز پیدا شد!

with a single `[🎁 باز کردن صندوق]` button. The **first** user to press it wins:
opening is one conditional `UPDATE ... WHERE status='available' AND opened_by
IS NULL`, so exactly one user can ever open a chest (verified with 12
simultaneous threads). The button is then removed, and unopened chests expire
after 15 minutes.

Rewards are rolled per chest from `config.CHEST_REWARDS`:

| Reward | Chance | Amount |
|--------|--------|--------|
| 🪨 ابسیدین | always | 100–2000 |
| ✨ اتر | 15% (rare) | 1–10 |
| 🥩 گوشت | 60% | 5–30 |
| 🐟 ماهی | 60% | 5–30 |

Food rewards are deposited **into the cold storage**; currencies go onto the
player row. Everything (credit + reward snapshot) happens in one transaction,
so a chest can never pay out twice.

Chests are stored in a new `chests` table: `id`, `group_id`, `message_id`,
`status` (available/opened/expired), `opened_by`, `created_time`,
`opened_time`, `reward` (JSON snapshot) and `is_test`.

**Admin support:** the panel gained `🎁 ساخت صندوق تست` (posts a real, openable
test chest marked `is_test`), game stats now report total/opened chests and the
total obsidian/aether in circulation, user info shows a player's balances, and
`🗑 پاک کردن اطلاعات تست` also removes test chests only.

Code: `models/chest.py`, `game/chests.py`, `handlers/chests.py`, job
`chest_tick` in `handlers/jobs.py`. Tests: `scripts/test_chests.py`.

## 🏪 Market (بازار)

`بازار` opens an inline market that sells **tool upgrades only**, priced in
**🪨 obsidian** (aether is never spent, and there is no selling).

```
🏪 بازار

💰 ۲۵۰۰ 🪨

انتخاب کن:
  [🎣 ابزار ماهیگیری]
  [🏹 ابزار شکار]
  [🔙]
```

Each button opens that tool's screen — current level, reward range and the
next cost — with a single `[⬆️ ارتقا]` button (see
[Tool progression](#-tool-progression-version-6)).

### Food and eggs are not for sale

Meat, fish and dragon eggs were removed from the shop on purpose:

| Resource | How it is obtained now |
| --- | --- |
| 🥩 گوشت | 🏹 hunting, 🎁 chests |
| 🐟 ماهی | 🎣 fishing, 🎁 chests |
| 🥚 تخم اژدها | random spawns, 🎁 rewards |

Only the **shop entries** are gone. Nothing was deleted from the game:

* the cold storage keeps every player's existing 🥩/🐟 and still accepts
  deposits from gathering and chests, and spends on feeding;
* the egg system is untouched — spawning, claiming, incubating, `تخم ها` and
  hatching all work exactly as before, and players keep the eggs they own.

`MARKET_ITEMS` therefore holds no buyable items, and `MarketService` only reads
the obsidian balance; `game.tools` performs the guarded spend for upgrades. The
old `buy` / `_buy_food` / `_buy_egg` paths and their item screens were removed
with them, so a stale «خرید» button from an old message is simply ignored — it
cannot grant food or eggs.

Code: `game/market.py`, `handlers/market.py`. Tests: `scripts/test_market.py`.

## 🥚 Egg spawn cooldown

Eggs used to appear far too often (a 40% roll every 3 minutes per group). Each
group now has its own **spawn cooldown**: after an egg appears, no further egg
can spawn in that group until `EGG_SPAWN_INTERVAL` has passed.

| Setting | Value |
|---------|-------|
| `EGG_SPAWN_INTERVAL` | **7200 s (2 hours)** by default |
| Env override | `DRAGON_EGG_SPAWN_INTERVAL` (e.g. `60` for testing) |
| Admin panel | `⏳ فاصله ظاهر شدن تخم` → 1 minute / 90 minutes / 2 hours / reset |

Example: Group A spawns at 12:00 → next possible 14:00, while Group B spawning
at 12:30 → next possible 14:30. The two timers are completely independent.

**How it works:** `chats.last_egg_spawn_time` (additive column, migrated in
place) records the last spawn per group, and the spawner claims its slot with a
single guarded `UPDATE ... WHERE last_egg_spawn_time IS NULL OR
last_egg_spawn_time <= now - interval`. Because the check and the write are one
statement, two ticks can never both spawn (verified with 12 concurrent
attempts), and because the timestamp is in the database the cooldown **survives
a bot restart**. If the egg cannot actually be created the slot is released, so
a group is never locked out for nothing.

Only the *frequency* changed — the claim button, egg storage, the one-egg-
per-group rule, incubation and hatching are all untouched. The runtime value
lives in `game/spawn_settings.py`. Tests: `scripts/test_spawn_cooldown.py`.

## 🛡️ Robust message sending

Scheduled jobs (egg spawner, chest spawner, hatch sweep) never crash when
Telegram is slow or unreachable:

- HTTP timeouts are raised at the application level (connect 15s, read/write 30s,
  `get_updates` 40s).
- All job announcements go through `handlers.chests.safe_send_message`, which
  retries `TimedOut` / `NetworkError` twice with backoff, honours `RetryAfter`
  flood control, and returns `None` instead of raising.
- Blocked bots (`Forbidden`) and invalid chat ids (`BadRequest`) are logged once
  and skipped without retrying.
- Every failed announcement is logged with the chat id and what was being sent.

Covered by `scripts/test_send_resilience.py`.

## ✨ Egg rarity & dragon origin (Version 8)

Eggs no longer produce identical dragons. When an egg hatches, two things are
rolled from the **egg's own tables**: the dragon's **element** and its
**rarity**. Rarity then scales the newborn's starting stats.

### Rarity ladder

| Rarity | Stats | Newborn HP / Power |
| --- | --- | --- |
| ⚪ معمولی | base | 100 / 20 |
| 🟢 کمیاب | +10 % | 110 / 22 |
| 🔵 حماسی | +25 % | 125 / 25 |
| 🟣 افسانه‌ای | +50 % | 150 / 30 |
| 🟡 اسطوره‌ای | +100 % | 200 / 40 |

Rarity is rolled **once**, stored in `dragons.rarity`, and never changes.
It only scales the *starting* stats — levelling, feeding, upgrades and the
arena all keep working on the resulting numbers exactly as before.

### Origin: element

Each egg either fixes its element (a 🔥 تخم شعله جاودان always yields a fire
dragon) or rolls one from its weighted pool (🥚 تخم کهن). Two new elements were
added for the new eggs: ⚡ صاعقه and 🌌 نخستین. See the
[egg table](#egg--dragon-types) for every type's element and chances.

🌌 **تخم اژدهای نخستین** has spawn weight 0, so it can *never* appear from a
wild spawn — it is reserved for special rewards, future events and rare drops.
`EggService.random_egg_type()` filters weight-0 eggs out of the spawn table
(covered by a 20 000-roll test).

### What the player sees

Hatching:

```
🎉 تخم باز شد!

🔥 تخم شعله جاودان ➜ 🔥 اژدهای آتشین

✨ کمیابی: 🔵 حماسی
❤️ HP: ۱۲۵   ⚔️ قدرت: ۲۵
👤 @Ali
```

The dragon page and the arena profile both gained an element and a rarity line:

```
🐉 آذر 🔥 ⭐

🔮 عنصر: 🔥 آتش
✨ کمیابی: 🔵 حماسی

⭐ Lv.۱
✨ XP: ۰/۱۰۰

❤️ HP: ۱۲۵/۱۲۵
⚔️ قدرت: ۲۵
🍖 گرسنگی: ۱۰۰٪
```

The dragon list prefixes each button with its rarity dot, so a 🟡 اسطوره‌ای
dragon is obvious at a glance: `[🟡 🌌 نخستین]`.

### Compatibility

`dragons.rarity` is added by `database/migrate.py` with
`DEFAULT 'normal'`, so **every existing dragon becomes ⚪ معمولی and keeps its
exact current level, XP, HP, power and hunger**. Eggs already incubating still
hatch: the three original egg keys (`common` / `rare` / `legendary`) were kept
untouched and simply gained a rarity table. Any blank or unknown rarity value
degrades to ⚪ معمولی rather than breaking a screen. Verified against a real
simulated V7 database.

Code: `game/rarity.py` (rules), `game/eggs.py` (rolling at hatch),
`game/dragons.py` (`create_newborn`), `models/dragon.py` (persistence).
Tests: `scripts/test_rarity.py` (160 checks).

## 🏟️ Arena PvP (Version 7)

**Version 7 removed the PvE combat system entirely.** The wolf / forest
monster / giant scorpion enemies, the «مبارزه» command, `game/combat.py`,
`handlers/battle.py`, `models/battle.py` and the `bt:` buttons are all gone,
along with the `battles` table (dropped automatically by `database/migrate.py`).
There are no NPC enemies in the game any more — dragons only fight *other
players' dragons*.

### The command

`/arena` (a real slash command) opens the menu:

```
🏟️ آرنا اژدها

🥉 لیگ برنز
🏅 ۲۵۰ امتیاز

⚔️ مبارزه‌های باقی‌مانده امروز:
۱۰/۱۰
  [⚔️ پیدا کردن حریف]
  [🏆 رتبه‌بندی]
  [🐉 اژدهای من]
  [🔙 برگشت]
```

Every button edits the same message in place — the arena never spams the group.

### Matchmaking

Pressing **⚔️ پیدا کردن حریف** takes the player's **active** dragon and looks
for another player whose active dragon is a fair opponent. Strength is a
single rating combining the three stats the design calls for:

```
rating = level × 10 + power × 3 + max_hp
```

A pair is acceptable when the level gap is within `ARENA_MATCH_LEVEL_SPREAD`
(3) **and** the rating gap is within `ARENA_MATCH_RATING_RATIO` (25 %) of the
stronger dragon. If nobody qualifies, the search widens **once** (6 levels /
50 %) so small groups can still play, then gives up with
«😕 حریف هم‌زور پیدا نشد!». A very weak dragon is therefore never matched
against a very strong one — a Lv.1 dragon and a Lv.30 dragon fail both windows.

Among the valid candidates the *closest* rating wins, with ties broken randomly
so the same two players do not always meet.

### The battle

The whole duel is simulated in one call and rendered as one message:

```
🏟️ نبرد آرنا شروع شد!

🐉 آذر
⭐ Lv.۱۰
❤️ HP: ۳۰۰
⚔️ Power: ۱۲۰

VS

🐉 شعله
⭐ Lv.۱۰
❤️ HP: ۲۹۰
⚔️ Power: ۱۱۸

━━━━━━━━━━

⚔️ آذر حمله کرد!
💥 ۵۶ آسیب وارد شد
⚔️ شعله حمله کرد!
💥 ضربه بحرانی! ۹۷ آسیب وارد شد
...
```

Per hit: `power × uniform(0.18, 0.42) + level × 0.5`, with a 12 % chance of a
×1.6 **ضربه بحرانی**, never less than 1 damage. Both dragons enter at full HP
and trade blows until one reaches 0; `ARENA_MAX_TURNS` (60) guarantees the loop
always terminates. Long fights are trimmed to the opening and closing
exchanges so the message stays readable.

**Initiative is a coin flip.** Striking first is a real advantage in an HP
race, so always giving it to the player who pressed the button skewed an even
match to ~76/24. Randomising it puts a mirror match back at ~50/50 (verified
over 400 seeded fights in `scripts/test_arena.py`).

Hunger still applies: a starving dragon fights at reduced power, exactly as
`effective_power` does everywhere else.

### No dragon ever dies

The fight runs on an in-memory snapshot of each dragon's stats. **The stored
`hp` column is never written by the arena**, so a loss costs no HP, needs no
healing, and cannot interfere with feeding, growth or upgrades. Losing only
costs arena points.

### Rewards

| Outcome | Arena points | Obsidian | XP |
| --- | --- | --- | --- |
| 🏆 Win | +25 | 400–600 | +30 |
| 💀 Loss | −10 | +100 | +10 |

```
🏆 برنده شدی!

🏅 +۲۵ امتیاز آرنا
🪨 +۵۰۰ ابسیدین
✨ +۳۰ تجربه

⚔️ باقی‌مانده امروز: ۹/۱۰
```

XP goes through the normal `DragonService.add_xp`, so arena wins can level a
dragon up just like hunting does. Points never fall below 0. The matched
opponent's win/loss record is updated too (so the ladder stays consistent) but
they receive no currency — only the player who fought spends a battle slot.

### Daily limit

`ARENA_DAILY_BATTLE_LIMIT` (10) battles per UTC day, tracked in
`players.arena_battles_today` + `arena_last_day`. The counter resets by itself
on the first action of a new day — no scheduled job. The slot is claimed with
a guarded `UPDATE ... WHERE arena_battles_today < limit`, so two simultaneous
taps can never exceed the cap, and a **failed search costs nothing**.

### Leagues & ranking

| League | Emoji | From |
| --- | --- | --- |
| برنز | 🥉 | 0 |
| نقره | 🥈 | 500 |
| طلا | 🥇 | 1500 |
| الماس | 💎 | 3000 |
| افسانه | 🐉 | 6000 |

**🏆 رتبه‌بندی** shows the top 10. The left medal is the *rank*; the badge after
the name is the player's *league*:

```
🏆 رتبه آرنا

🥇 Kian 🥇
🏅 امتیاز: ۲۵۰۰

🥈 Reza 🥇
🏅 امتیاز: ۲۰۰۰

🥉 Sara 🥈
🏅 امتیاز: ۱۵۰۰

📍 رتبه تو: ۴
```

**🐉 اژدهای من** shows the active dragon's stats plus league, points, W/L,
rank, the points still needed for the next league, and today's remaining
battles.

### Database

`players` gains `arena_points`, `arena_wins`, `arena_losses`,
`arena_battles_today` and `arena_last_day`; the new `arena_battles` table is an
append-only history of finished duels. Existing players are migrated in place
and start unranked (all zeros) with **every other column untouched** — meat,
fish, obsidian, aether, rod/weapon levels and dragons all survive, verified by
a real V6-database upgrade test.

> Note: the leaderboard index on `players(arena_points)` is created in
> `database/migrate.py`, *not* `schema.sql` — `schema.sql` runs before the
> migrations, so on an upgraded database the column does not exist yet.

Code: `game/arena.py` (rules), `handlers/arena.py` (UI), `models/arena.py`
(history), `models/player.py` (points/limits). Tests: `scripts/test_arena.py`
(124 checks).

## 🔁 Duplicate instance (Conflict) handling

Telegram allows only **one** `getUpdates` consumer per bot token. If a second
copy of the bot is started, every poll raises
`telegram.error.Conflict: terminated by other getUpdates request`.

The bot now handles this gracefully:

- The application error handler recognises `Conflict` and logs one clear
  explanation (what happened, that only one instance may run, and how to fix
  it — stop the other process or `deleteWebhook`), with no traceback.
- `handlers.errors.ConflictLogFilter` (installed from `bot.py` at startup)
  also collapses the tracebacks python-telegram-bot's own polling loop prints,
  since those never reach the error handler.
- Repeats are throttled: after the first message, a reminder is logged at most
  once every `CONFLICT_LOG_INTERVAL_SECONDS` (300s) and reports how many
  occurrences were suppressed. Suppressed ones stay visible at DEBUG level.
- The bot is **not** stopped — polling keeps retrying and recovers by itself
  once the duplicate instance is shut down.
- Normal startup, architecture and all other error handling are unchanged;
  timeouts still log as warnings and genuine bugs still log a full traceback
  and notify the user.

Tests: `scripts/test_conflict.py` (20 checks).


## ⭐ Selected dragon vs. active dragon

پیش‌تر انتخاب یک اژدها از «اژدها» به‌طور خودکار آن را **اژدهای فعال**
می‌کرد؛ یعنی اگر فقط می‌خواستی به «آذر» غذا بدهی، اژدهای فعالت هم عوض می‌شد.
این رفتار اشتباه بود و اصلاح شد. حالا دو مفهوم کاملاً جدا هستند:

| | Selected dragon | Active dragon |
|---|---|---|
| محل ذخیره | `context.user_data` (موقت، فقط همین تعامل) | `players.active_dragon_id` (دائمی) |
| چه چیزی عوضش می‌کند | باز کردن صفحه‌ی اژدها | فقط دکمه‌ی «⭐ انتخاب به عنوان فعال» |
| کاربرد | دیدن مشخصات، غذا دادن، ارتقا، تغییر نام | نماینده‌ی بازیکن در بقیه‌ی بازی (آرنا) |

- انتخاب اژدها از لیست **فقط** پروفایلش را باز می‌کند.
- غذا دادن / ارتقا / تغییر نام روی همان اژدهای انتخاب‌شده اعمال می‌شود و
  اژدهای فعال دست‌نخورده می‌ماند.
- دکمه‌ی «⭐ انتخاب به عنوان فعال» تنها راه تغییر اژدهای فعال است و پیام
  «⭐ <نام> اکنون اژدهای فعال شماست.» را نشان می‌دهد.
- در لیست، اژدهای فعال با ✅ و در پروفایلش با خط «⭐ اژدهای فعال تو» مشخص است.
- «🔙 برگشت» انتخاب موقت را پاک می‌کند (اژدهای فعال بدون تغییر می‌ماند).
- سیستم آرنا فقط `active_dragon_id` را می‌خواند.

ساختار دیتابیس تغییری نکرد: `selected_dragon_id` عمداً در دیتابیس ذخیره
نمی‌شود چون حالت موقتِ نشست است (`game/selection.py`).

تست‌ها: `scripts/test_selection.py` (۵۵ بررسی).


## 🔤 Command rename + chest message editing

**۱. دستور «اژدها»** — نام دستور مدیریت اژدهاها از «اژدها های من» به **«اژدها»**
تغییر کرد. دستور قدیمی (و نام مستعار «اژدهاهای من») کاملاً حذف شد. خود سیستم
دست‌نخورده است: همان لیست انتخاب، همان selected/active dragon، همان غذا دادن،
ارتقا و تغییر نام.

```
اژدها
↓
🐉 اژدهای خود را انتخاب کنید:
[🔥 آذر] [❄️ یخ پنجه] [🌑 رعد]
```

**۲. ویرایش پیام صندوق** — وقتی کاربر «🎁 باز کردن صندوق» را می‌زند، ربات دیگر
پیام جدید نمی‌فرستد؛ **همان پیام اصلی صندوق ویرایش می‌شود** و دکمه‌اش حذف
می‌گردد:

```
🎁 صندوق باز شد!

👤 باز کننده:
User Name

Rewards:

🪨 +۸۵۰ ابسیدین
✨ +۳ اتر
🥩 +۱۰ گوشت
🐟 +۱۵ ماهی
```

`chests.message_id` از قبل هنگام ظاهر شدن صندوق ذخیره می‌شد و حالا به‌عنوان
مسیر پشتیبان استفاده می‌شود: اگر ویرایش از طریق callback ممکن نباشد، ربات با
همان `message_id` ذخیره‌شده پیام را ویرایش می‌کند. منطق جایزه‌ها و دیتابیس
تغییری نکرده و همچنان فقط اولین کاربر می‌تواند صندوق را باز کند.

تست‌ها: `scripts/test_chest_edit.py` (۴۶ بررسی).


## 🎨 Compact UI style

همه‌ی پیام‌ها به سبک رابط بازی موبایلی بازنویسی شدند: عنوان → آمار مهم →
دکمه‌ها. توضیحات اضافی و جمله‌های بلند حذف شدند و ایموجی‌ها نقش آیکون دارند.
**هیچ منطقی تغییر نکرد** — فقط متن‌ها و برچسب دکمه‌ها.

پروفایل اژدها:

```
🐉 آذر 🔥 ⭐

⭐ Lv.۵
✨ XP: ۲۵۰/۵۰۰

❤️ HP: ۱۸۰/۲۰۰
⚔️ قدرت: ۴۵
🍖 گرسنگی: ۷۰٪

[🥩 غذا] [⬆️ ارتقا]
[✏️ نام] [⭐ فعال]
[🔙]
```

سایر صفحه‌ها: `🐉 انتخاب اژدها:` (فقط دکمه‌ها)، `❄️ سردخانه`،
`🏪 بازار` با دکمه‌های `🥩 غذا / 🥚 تخم / ✨ ویژه`، `⬆️ ارتقا <نام>`،
`🥚 تخم اژدها پیدا شد!` و کارت‌های کوتاه نبرد/شکار/ماهیگیری.

نکته‌ها:
- ستارهٔ `⭐` کنار نام اژدها یعنی «اژدهای فعال» (به‌جای یک خط توضیح).
- `⚠️` کنار قدرت/گرسنگی یعنی اژدها گرسنه است و ضعیف‌تر می‌جنگد.
- برچسب کوتاه دکمه‌ها از کلیدهای نمایشی `short` در `config.UPGRADES` و
  `config.MARKET_CATEGORIES` می‌آید؛ قیمت‌ها و مقادیر دست‌نخورده‌اند.


## 🔔 Event & notification messages

پیام‌های رویدادی هم کوتاه و بازی‌گونه شدند (۲ تا ۵ خط، بدون کلمه‌ی تکراری،
با اعداد مهم و ایموجی). فقط متن‌ها عوض شدند — منطق، دیتابیس و دکمه‌ها
دست‌نخورده‌اند.

```
🎁 صندوق باز شد!      🥩 آذر غذا خورد!     🏹 شکار موفق!
                                          
👤 Ali                🍖 ۷۰٪ ➜ ۱۰۰٪       🦌 گوزن شکار شد!
                                          🥩 +۱۵ گوشت
🪨 +۵۰۰
✨ +۲                 🎣 ماهیگیری موفق!    🏆 پیروزی!
🥩 +۱۰                                    
                      🐟 +۱۵ ماهی         ⭐ +۲۵ XP
                                          🪨 +۱۰۰
```

- صندوق: `🎁 صندوق پیدا شد!` → بعد از باز شدن همان پیام به کارت جایزه با
  `👤 <نام>` و فهرست `+عدد` تبدیل می‌شود (بدون تکرار نام واحد پول).
- غذا: `🍖 ۷۰٪ ➜ ۱۰۰٪`؛ وقتی سیر است فقط `🐉 <نام> سیره!`.
- نبرد: شروع در یک خط `🐉 آذر VS 👹 هیولا`، حمله `🔥 ۲۵ Damage`،
  برد `🏆 پیروزی!` با `⭐ +XP` و `🪨 +عدد`.
- لِوِل‌آپ: `🎉 Level Up!` + `🔥 آذر ➜ Lv.۶` + `❤️ +۲۰   ⚔️ +۵`.
- تخم: `🥚 تخم برداشته شد!` و بعد از باز شدن `🐣 تخم باز شد!`.

### 🎉 Shared reward card

All rewards render through one helper, `utils.text.reward_card()`, so a chest,
a battle win and an admin grant look identical:

```
🎉 جایزه گرفتی!

🪨 +۵۰۰
✨ +۳
```

`reward_card(rewards, title=..., who=...)` swaps the title and adds a
`👤 <name>` line — that is how the chest message is built:

```
🎁 صندوق باز شد!

👤 Ali

🪨 +۵۰۰
✨ +۲
🥩 +۱۰
```

Zero amounts are skipped and the order (`⭐ 🪨 ✨ 🥩 🐟`) is fixed, so rewards
never shuffle between messages. `scripts/test_messages.py` pins both formats.

## ⏳ Temporary eggs & chests (Version 5)

Eggs and chests no longer stay in a group forever. Both follow the same
lifecycle, and both use **one message only**.

**Egg spawns** — a single message with a single button:

```
🥚 یک تخم اژدها پیدا شد!
[🥚 نگهداری از تخم]
```

**A player collects it** — the *same* message is edited in place, the button is
removed and no new message is sent:

```
🥚 تخم برداشته شد!

👤 بازیکن: Ali
```

Chests behave identically (`🎁 صندوق پیدا شد!` → the reward card).

### Timers

| Setting | Default | Meaning |
| --- | --- | --- |
| `CHEST_EXPIRE_TIME` | 30 min | Unopened chest: message deleted, chest removed from play |
| `EGG_EXPIRE_TIME` | 30 min | Uncollected egg: message deleted, egg removed from play |
| `MESSAGE_DELETE_TIME` | 5 min | After a successful open/collect, the result message is deleted |

Each can be overridden with the `DRAGON_CHEST_EXPIRE_TIME`,
`DRAGON_EGG_EXPIRE_TIME` and `DRAGON_MESSAGE_DELETE_TIME` environment
variables. `CHEST_OPEN_WINDOW_SECONDS` and `CLAIM_WINDOW_SECONDS` are derived
from the two expire times, so a button can never outlive its message.

### How the timers survive a restart

Deadlines are **absolute timestamps stored in the database** (`eggs.delete_after`
and `chests.delete_after`), not in-memory jobs. The `cleanup_tick` job runs
every 30 s and simply asks the database which messages are now due — so a
cleanup scheduled before a reboot still happens afterwards. Both columns are
added to existing databases by `database/migrate.py`.

Duplicate claims remain impossible: collecting an egg and opening a chest are
each a single conditional `UPDATE`, so exactly one user can ever win. Every
group is swept independently, and a failure in one group never aborts the
sweep. Covered by `scripts/test_temporary.py` (43 checks).

## 🏰 Dragon Treasury (خزانه)

A read-only inventory screen. Send **`خزانه`**:

```
🏰 خزانه اژدها

🪨 ابسیدین: ۱۵۰۰
✨ اتر: ۷
[🥩 غذا]
[🥚 تخم‌ها]
```

`[🥩 غذا]` and `[🥚 تخم‌ها]` **edit the same message** (no new messages), and
`[🔙 برگشت]` returns:

```
❄️ سردخانه            🥚 تخم‌های من:

🥩 گوشت: ۵۰           🥚 تخم معمولی: ۳
🐟 ماهی: ۸۰           💎 تخم کمیاب: ۱
                      👑 تخم افسانه‌ای: ۰
```

Every configured egg type is always listed, so a type the player does not hold
shows `۰` instead of disappearing.

### No duplicated storage

`game/treasury.py` owns **no data**. It is a pure aggregation layer that reads
what the existing systems already maintain:

| Shown | Read from |
| --- | --- |
| 🪨 ابسیدین / ✨ اتر | `players.obsidian` / `players.aether` |
| 🥩 گوشت / 🐟 ماهی | `ColdStorageService` (the single owner of meat/fish) |
| 🥚 eggs | `eggs` table, grouped by type (`count_incubating_by_type`) |

Nothing in the treasury writes to the database, so it can never desync from
the cold storage, market, chest or arena systems — a chest opened a second
earlier is already reflected. The test suite asserts the values match
`ColdStorageService` and the player row exactly, and that browsing every screen
leaves all player data byte-identical.

Callback namespace is `tr:` (no collision with `dg:`, `mk:`, `bt:`, `admin:`,
`open_chest:`, `claim_egg:`). Covered by `scripts/test_treasury.py` (51 checks).

## 📈 Progressive upgrade costs

The ⭐ level upgrade is no longer a flat price: it scales with the dragon's
**current** level, so late levels are a real goal instead of a repeat of the
first one.

| Level | Cost | Level | Cost |
| --- | --- | --- | --- |
| 1 → 2 | 🪨 1 000 | 6 → 7 | 🪨 12 000 |
| 2 → 3 | 🪨 2 000 | 7 → 8 | 🪨 18 000 |
| 3 → 4 | 🪨 3 500 | 8 → 9 | 🪨 27 000 |
| 4 → 5 | 🪨 5 500 | 9 → 10 | 🪨 40 000 |
| 5 → 6 | 🪨 8 000 | | |

From level 10 upward the cost is extrapolated:

```
upgrade_cost = round(40000 * (current_level / 10) ** 1.8)
```

Levels 1–9 come from the hand-tuned `config.UPGRADE_COST_TABLE`; the formula
takes over at `UPGRADE_COST_FORMULA_FROM` (10). Both give 40 000 at level 10,
so the curve never drops — levels 9 and 10 share a price, which is the single
intentional plateau where the table hands over to the formula.

`game.upgrades.level_upgrade_cost(level)` is the one source of truth, used by
the service, the upgrade card and the buttons alike, so a price can never be
advertised in the UI that differs from what is charged. The price is resolved
from the dragon row **inside the same transaction as the guarded spend**, so a
double tap can never be charged at a stale (cheaper) level.

❤️ HP and ⚔️ power keep their flat `cost_obsidian` prices. The XP system,
per-level stat bonuses and the database schema are unchanged.

```
⬆️ ارتقای اژدها          ⬆️ ارتقا موفق!         ❌ ابسیدین کافی نداری!

🐉 آذر                   ⭐ Level:              نیاز:
⭐ Level: ۵              ۵ ➜ ۶                  🪨 ۱۲۰۰۰
```

Covered by `scripts/test_upgrade_costs.py` (67 checks).

## 🎣🏹 Tool progression (Version 6)

Every player owns a **🎣 fishing rod** and a **🏹 hunting weapon**, both starting
at Lv.1. A tool's level sets the reward range of its gathering action, and the
weapon also decides which prey can be caught. Upgrades are paid in 🪨 obsidian,
one level at a time, capped at Lv.10.

| Lv | 🎣 Rod | 🐟 Fish | 🏹 Weapon | 🥩 Meat | 🪨 Cost |
| --- | --- | --- | --- | --- | --- |
| 1 | قلاب چوبی | 5–10 | تیرکمان | 3–6 | — |
| 2 | قلاب آهنی | 8–15 | کمان چوبی | 5–10 | 2 000 |
| 3 | قلاب فولادی | 12–20 | کمان آهنی | 8–15 | 5 000 |
| 4 | قلاب طلایی | 15–25 | کمان فولادی | 12–20 | 10 000 |
| 5 | قلاب جادویی | 20–30 | کمان جادویی | 18–30 | 20 000 |
| 6 | قلاب کریستالی | 25–40 | تفنگ شکاری | 25–40 | 35 000 |
| 7 | قلاب اقیانوس | 35–50 | تفنگ پیشرفته | 35–55 | 60 000 |
| 8 | قلاب باستانی | 45–65 | سلاح انرژی | 50–70 | 100 000 |
| 9 | قلاب افسانه‌ای | 60–85 | سلاح باستانی | 70–100 | 170 000 |
| 10 | قلاب اژدها | 80–120 | سلاح اژدها | 100–150 | 300 000 |

**Prey unlocking:** Lv.1 catches 🐇 rabbit only, Lv.2 adds 🦌 deer, Lv.3+ adds
🦌 gazelle. A higher weapon never hunts fewer animals.

### Where it lives

* `config.FISHING_RODS` / `config.HUNTING_WEAPONS` — the tables above.
* `game/tools.py` — `ToolService` (levels, costs, upgrades) plus
  `reward_range()` and `allowed_prey()`. No Telegram imports.
* `players.rod_level` / `players.weapon_level` — added by
  `database/migrate.py`, so **existing players are upgraded in place and start
  at Lv.1**, exactly like new ones.
* `game/actions.py` reads the level and rolls the matching range; cooldowns,
  egg chances and XP are untouched.

### Market & treasury

`🏪 بازار` gains `[🎣 ابزار ماهیگیری]` and `[🏹 ابزار شکار]`. Each shows the
current tool, its reward range and the next cost, with one `[⬆️ ارتقا]` button
(hidden at Lv.10):

```
🎣 ابزار ماهیگیری          🎉 ارتقا موفق!         🏰 خزانه اژدها

🎣 قلاب فعلی:              🎣 قلاب:               🪨 ابسیدین: ۵۰۰
Lv.۱ — قلاب چوبی           Lv.۱ ➜ Lv.۲            ✨ اتر: ۳
🐟 ۵-۱۰                    ✨ قلاب آهنی
                                                  🎣 قلاب: Lv.۲
⬆️ ارتقا: 🪨 ۲۰۰۰          🪨 -۲۰۰۰   💰 ۵۰۰       🏹 ابزار شکار: Lv.۱
```

Too poor → `❌ ابسیدین کافی نیست!`; at the cap → `🏆 حداکثر سطحه!`.

### Safety

Payment and the level increment are ONE guarded `UPDATE` that also re-checks
the current level and the cap, so concurrent taps cannot skip a level,
overspend or exceed Lv.10 — verified with 10 simultaneous upgrades against a
balance for exactly one. Levels are clamped on read, so a corrupt row can never
crash gathering or pay out a huge reward. No durability, crafting or trading.

Covered by `scripts/test_tools.py` (124 checks).
