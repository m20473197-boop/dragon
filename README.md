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
| `اژدهای من` | My dragons       | Shows each dragon's نام (name), نوع (type), ⭐ سطح (level), ✨ تجربه (current/required XP), ❤️ سلامت (HP), 🔥 قدرت (power). |
| `اژدها های من` | Dragon management | Selection-first panel: one inline button per dragon, then that dragon's profile with 🥩 غذا دادن / ⬆️ ارتقا / ✏️ تغییر نام / 🔙 برگشت. **All feeding happens here.** |
| `نام اژدها` | Name dragon      | The bot asks for a name; your next message names your most recent dragon. Sending a game command cancels it. |
| `غذا بده`   | Feed dragon      | Shows your stored 🥩/🐟 with buttons to feed your newest dragon (consumes food, heals, grants XP, restores hunger). |
| `سردخانه`   | Cold storage     | Shows your ❄️ سردخانه (cold storage): stored 🥩 گوشت and 🐟 ماهی. |

### Cold storage (سردخانه)

Every player has a basic **❄️ سردخانه** (cold storage) that holds their food —
🥩 meat and 🐟 fish. It is deliberately simple: **no levels, no upgrades and no
capacity limits**.

- Hunting deposits meat **directly into cold storage**; fishing deposits fish
  **directly into cold storage**.
- Feeding (`غذا بده`) consumes food **from cold storage**.

The amounts live on the player record (`players.meat` / `players.fish`, also
shown by `تخم ها`/`اژدهای من`); the named `game/storage.py::ColdStorageService`
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
  (`game/dragons.py::effective_power`, ready for combat).
- **Feeding (`غذا بده`):** shows your food and two buttons:
  - 🥩 **گوشت** — consumes 3 meat → restores hunger, +HP, +XP
  - 🐟 **ماهی** — consumes 5 fish → restores hunger, +HP, +XP

  Food is spent atomically (`spend_resource`, guarded `UPDATE`), so rapid taps
  can never over-spend. Feeding XP can trigger level-ups (+max HP/power and full
  heal). Logic lives in `game/feeding.py` (`FeedingService`).

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
  single XP grant can cross multiple levels and is applied atomically. No
  combat/PvP yet — the same `add_xp` entry point is ready for future battles.

### Dragon data system

When an egg hatches, a new dragon row is created for the owner with a random
type (from the egg's rarity pool) and default stats:

- **name:** `بدون نام` (unnamed — ready for a future rename feature)
- **type:** random dragon type (e.g. 🔥 اژدهای آتشین)
- **level:** 1 · **xp:** 0 · **hp / max_hp:** 100 / 100 · **power:** 20

The `dragons` table stores `id, owner_id, name, type, level, xp, hp, max_hp,
power` (plus `from_egg_id`, `born_at`). On startup `database/migrate.py`
adds any missing columns to older databases, so existing installs upgrade in
place. Dragon creation/reading lives in `game/dragons.py` (`DragonService`);
no combat or PvP yet.

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

| Egg type            | Weight | Incubation | Can hatch into                     |
|---------------------|-------:|-----------:|------------------------------------|
| 🥚 معمولی (common)   | 70%    | 15 min     | 🐲 سبز / 🔥 آتشین / ❄️ یخی          |
| 💎 کمیاب (rare)      | 25%    | 45 min     | 🔥 آتشین / ❄️ یخی / ✨ طلایی / 🌑 سایه |
| 👑 افسانه‌ای (legendary) | 5% | 2 hours   | ✨ طلایی / 🌑 سایه                  |

All numbers, weights, timings and names live in `config.py`.

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
│   └── dragon.py           # DragonRepository
├── game/                   # Rules only — no Telegram imports
│   ├── actions.py          # hunt(), fish() (atomic reward + cooldown)
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
│   └── eggs.py             # تخم ها
├── utils/
│   ├── text.py             # Persian digits, cooldown text, command normalization
│   └── rng.py              # weighted_choice() helper
└── scripts/
    ├── smoke_test.py       # Tests DB + game logic (full egg lifecycle)
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
```

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

Implemented in `handlers/dragon_manage.py`; `FeedingService.feed()` gained an
optional `dragon_id` argument (default behaviour of `غذا بده` is unchanged).
Tests: `scripts/test_dragon_manage.py`.

## 🥩 Feeding system (dragon page only)

The standalone `غذا بده` command is **retired**: it now just points players to
the dragon page, and leftover food buttons from old messages no longer feed.
Feeding is reached only through `اژدها های من` → select a dragon → `🥩 غذا دادن`,
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

`⬆️ ارتقا` on a dragon's page upgrades **only that dragon**, paid with food from
cold storage (no coins, shops or currency). Defined in `config.UPGRADES`, so
costs, bonuses and new upgrade types are configuration changes only:

| Upgrade | Effect | Default cost |
|---------|--------|--------------|
| ❤️ افزایش سلامت | +20 max HP (and a full heal) | 10 🥩 + 5 🐟 |
| 🔥 افزایش قدرت | +5 power | 8 🥩 + 8 🐟 |
| ⭐ افزایش سطح | +1 level (with the usual per-level HP/power gains) | 20 🥩 + 20 🐟 |

Implemented in `game/upgrades.py`; affordability is checked before anything is
spent, and ownership is enforced on every apply.

## 🎯 Active dragon

`players.active_dragon_id` (additive column, migrated in place) stores **one**
active dragon per user. Selecting a dragon from the list makes it active — it is
marked with ✅ in the selection list — and the first dragon to hatch becomes
active automatically. Setting it is guarded by an ownership check, and the
pointer is cleared if that dragon is removed. Nothing else depends on it yet;
it is in place for future features.

Tests: `scripts/test_feeding_v3.py` (feeding, upgrades, active dragon).
