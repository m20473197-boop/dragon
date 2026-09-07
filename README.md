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
| `نام اژدها` | Name dragon      | The bot asks for a name; your next message names your most recent dragon. Sending a game command cancels it. |

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
