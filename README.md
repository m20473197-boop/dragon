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
  (`game/dragons.py::effective_power`, ready for combat).
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

`بازار` opens an inline market. Everything is priced in **🪨 obsidian only** —
aether is never spent, and there is no selling and no chest shop.

> 🏪 بازار اژدها
>
> 💰 موجودی تو: 🪨 ۱۲۰۰ ابسیدین

| Category | Contents |
|----------|----------|
| 🥩 غذا | 🥩 گوشت — ۱۰ عدد for 🪨 ۵۰ · 🐟 ماهی — ۱۰ عدد for 🪨 ۴۰ |
| 🥚 تخم اژدها | 🥚 تخم معمولی for 🪨 ۸۰۰ |
| ✨ آیتم‌های ویژه | Empty — reserved for future items |
| 🔙 برگشت | Back to the category list |

Each item has its own buy button. On success the message is edited to:

> ✅ خرید انجام شد!
>
> 🥩 ۱۰ گوشت به سردخانه‌ات اضافه شد.
> 💸 پرداختی: 🪨 ۵۰ ابسیدین · 💰 موجودی جدید: 🪨 ۱۱۵۰ ابسیدین

**Food** is deposited into the cold storage. **Eggs** are created through the
existing egg pipeline (`EggService.create_found_egg`, forced to the purchased
type), so a bought egg is owned, incubating, counted in `players.eggs`, listed
by `تخم ها` and hatched by the normal hatch sweep — no new egg mechanics.

**Safety:** payment uses a guarded `spend_currency` UPDATE
(`... WHERE obsidian >= price`), so a balance can never go negative and ten
simultaneous taps yield exactly one purchase (covered by the tests). If egg
creation ever fails, the obsidian is refunded.

Prices, amounts and new items live in `config.MARKET_ITEMS` — extending the
market (including filling the special category) is a configuration change.
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

## ⚔️ Combat system (نسخه ۴)

دستور **«مبارزه»** اژدهای *فعال* بازیکن را به جنگ یک دشمن تصادفی می‌فرستد.
اگر بازیکن اژدهای فعال نداشته باشد پیام «🐉 ابتدا یک اژدها را انتخاب کنید.»
نمایش داده می‌شود و هیچ نبردی شروع نمی‌شود.

### دشمن‌ها (`config.ENEMIES`)

| دشمن | ❤️ HP | ⚔️ Power | 🪨 جایزه | ⭐ XP |
|------|------|---------|---------|------|
| 🐺 گرگ وحشی | ۸۰ | ۱۰ | ۶۰–۱۴۰ | ۱۵–۲۵ |
| 👹 هیولای جنگل | ۱۲۰ | ۱۶ | ۱۲۰–۲۶۰ | ۲۵–۴۰ |
| 🦂 عقرب غول پیکر | ۱۰۰ | ۲۲ | ۱۵۰–۳۲۰ | ۳۰–۵۰ |

دشمن‌ها با وزن انتخاب می‌شوند؛ برای افزودن دشمن جدید فقط کافی است یک ورودی
به `ENEMIES` اضافه شود.

### جریان نبرد

پیام نبرد دو دکمه دارد: **⚔️ حمله** و **🏃 فرار**.

- **حمله:** آسیب اژدها = `effective_power(power, hunger)` + یک عدد تصادفی
  (`BATTLE_DAMAGE_BONUS_MIN..MAX`). اگر دشمن زنده بماند، با
  `attack_power ± BATTLE_ENEMY_DAMAGE_SPREAD` ضربه می‌زند. گرسنگی روی قدرت
  اثر می‌گذارد (همان سیستم قبلی).
- **پیروزی:** ⭐ تجربه (از طریق `DragonService.add_xp`، پس لِوِل‌آپ عادی کار
  می‌کند)، 🪨 ابسیدین، و با شانس `BATTLE_AETHER_CHANCE` مقداری ✨ اتر.
- **شکست:** اژدها هرگز حذف نمی‌شود؛ فقط ضعیف می‌شود و HP آن روی
  `BATTLE_DRAGON_MIN_HP` می‌ماند. با غذا دادن دوباره قوی می‌شود.
- **فرار:** نبرد بدون جایزه و بدون ذخیره‌ی پیشرفت تمام می‌شود.

### پایگاه داده

جدول `battles` (`battle_id, user_id, dragon_id, chat_id, message_id, enemy_id,
enemy_hp, enemy_max_hp, status, turns, created_time, updated_time,
finished_time, reward`). نبرد در دیتابیس ذخیره می‌شود، پس **ری‌استارت شدن
بات آن را از بین نمی‌برد**.

### محافظت در برابر اسپم

- ایندکس یکتای جزئی `idx_battles_one_active` تضمین می‌کند هر کاربر در هر لحظه
  فقط **یک** نبرد فعال دارد.
- هر حمله با `UPDATE ... WHERE status='active' AND turns=?` اعمال می‌شود، پس
  دو بار فشردن همزمان دکمه فقط یک نوبت را اجرا می‌کند.
- شناسه‌ی نبرد داخل `callback_data` است و مالکیت در هر کلیک دوباره بررسی
  می‌شود؛ کاربر دیگر پیام «⛔ این نبرد مال تو نیست!» می‌گیرد.
- دکمه‌های نبرد تمام‌شده کار نمی‌کنند و پاک می‌شوند.
- نبردهای رهاشده بعد از `BATTLE_STALE_SECONDS` آزاد می‌شوند تا کاربر قفل نشود.

تست‌ها: `scripts/test_combat.py` (۸۰ بررسی).

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
| کاربرد | دیدن مشخصات، غذا دادن، ارتقا، تغییر نام | نماینده‌ی بازیکن در بقیه‌ی بازی (مبارزه) |

- انتخاب اژدها از لیست **فقط** پروفایلش را باز می‌کند.
- غذا دادن / ارتقا / تغییر نام روی همان اژدهای انتخاب‌شده اعمال می‌شود و
  اژدهای فعال دست‌نخورده می‌ماند.
- دکمه‌ی «⭐ انتخاب به عنوان فعال» تنها راه تغییر اژدهای فعال است و پیام
  «⭐ <نام> اکنون اژدهای فعال شماست.» را نشان می‌دهد.
- در لیست، اژدهای فعال با ✅ و در پروفایلش با خط «⭐ اژدهای فعال تو» مشخص است.
- «🔙 برگشت» انتخاب موقت را پاک می‌کند (اژدهای فعال بدون تغییر می‌ماند).
- سیستم مبارزه فقط `active_dragon_id` را می‌خواند.

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
