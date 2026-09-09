-- Dragon bot database schema.
-- Safe to run repeatedly (all statements use IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS players (
    user_id           INTEGER PRIMARY KEY,          -- Telegram user ID
    username          TEXT,                          -- Telegram @username (without @)
    meat              INTEGER NOT NULL DEFAULT 0,    -- گوشت
    fish              INTEGER NOT NULL DEFAULT 0,    -- ماهی
    eggs              INTEGER NOT NULL DEFAULT 0,    -- count of incubating eggs (eggs owned)
    dragons           INTEGER NOT NULL DEFAULT 0,    -- total dragons owned
    last_hunt_time    REAL,                          -- unix timestamp of last hunt
    last_fishing_time REAL,                          -- unix timestamp of last fishing
    hunt_count        INTEGER NOT NULL DEFAULT 0,    -- total successful hunts
    fishing_count     INTEGER NOT NULL DEFAULT 0,    -- total successful fishing trips
    active_dragon_id  INTEGER,                       -- currently selected/active dragon (one per user)
    obsidian          INTEGER NOT NULL DEFAULT 0,    -- 🪨 ابسیدین (main currency)
    aether            INTEGER NOT NULL DEFAULT 0,    -- ✨ اتر (rare currency)
    rod_level         INTEGER NOT NULL DEFAULT 1,    -- 🎣 fishing rod level (V6)
    weapon_level      INTEGER NOT NULL DEFAULT 1,    -- 🏹 hunting weapon level (V6)
    arena_points        INTEGER NOT NULL DEFAULT 0,  -- 🏅 arena rating points (V7)
    arena_wins          INTEGER NOT NULL DEFAULT 0,  -- 🏆 arena victories (V7)
    arena_losses        INTEGER NOT NULL DEFAULT 0,  -- 💀 arena defeats (V7)
    arena_battles_today INTEGER NOT NULL DEFAULT 0,  -- daily limit counter (V7)
    arena_last_day      TEXT,                        -- UTC day of the counter (V7)
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_players_username ON players (username);

-- Groups the bot is active in (used by the egg spawner).
CREATE TABLE IF NOT EXISTS chats (
    chat_id    INTEGER PRIMARY KEY,                 -- Telegram group chat ID
    title      TEXT,
    last_seen  REAL NOT NULL,                       -- unix timestamp of last activity
    last_egg_spawn_time REAL                        -- unix timestamp of the last egg spawned here
);

CREATE INDEX IF NOT EXISTS idx_chats_last_seen ON chats (last_seen);

-- Dragon eggs, spawned in groups or found while gathering.
CREATE TABLE IF NOT EXISTS eggs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    egg_type    TEXT NOT NULL,                      -- key from config.EGG_TYPES
    chat_id     INTEGER NOT NULL,                   -- group it appeared in
    message_id  INTEGER,                            -- spawn message (for button updates)
    owner_id    INTEGER,                            -- Telegram user ID of claimer (NULL until claimed)
    status      TEXT NOT NULL DEFAULT 'available',  -- available | incubating | hatched | expired
    is_test     INTEGER NOT NULL DEFAULT 0,         -- 1 if created via the admin test tools
    spawn_time  REAL NOT NULL,
    claim_time  REAL,
    hatch_time  REAL,                               -- set when claimed (spawn_time for found eggs)
    delete_after REAL,                              -- when the message must be deleted (V5)
    FOREIGN KEY (owner_id) REFERENCES players (user_id)
);

CREATE INDEX IF NOT EXISTS idx_eggs_status_hatch ON eggs (status, hatch_time);
CREATE INDEX IF NOT EXISTS idx_eggs_owner ON eggs (owner_id, status);
CREATE INDEX IF NOT EXISTS idx_eggs_chat ON eggs (chat_id, status);

-- Dragons born from hatched eggs.
CREATE TABLE IF NOT EXISTS dragons (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id     INTEGER NOT NULL,                   -- Telegram user ID of the owner
    name         TEXT NOT NULL,                      -- display name (default: بدون نام)
    dragon_type  TEXT NOT NULL,                      -- key from config.DRAGON_TYPES
    level        INTEGER NOT NULL DEFAULT 1,
    xp           INTEGER NOT NULL DEFAULT 0,
    hp           INTEGER NOT NULL DEFAULT 100,       -- current health
    max_hp       INTEGER NOT NULL DEFAULT 100,
    power        INTEGER NOT NULL DEFAULT 20,        -- base attack power
    hunger       INTEGER NOT NULL DEFAULT 100,       -- fullness 0..100 (100 = full)
    rarity       TEXT NOT NULL DEFAULT 'normal',      -- V8: key from config.RARITIES
    breeding_status      TEXT NOT NULL DEFAULT 'idle', -- V9: idle | breeding
    breeding_finish_time REAL,                         -- V9: when the ritual ends
    parent_dragon_1      INTEGER,                      -- V9: first parent
    parent_dragon_2      INTEGER,                      -- V9: second parent
    last_fed_time REAL,                              -- unix timestamp of last feeding
    is_test      INTEGER NOT NULL DEFAULT 0,         -- 1 if created via the admin test tools
    from_egg_id  INTEGER,
    born_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (owner_id)   REFERENCES players (user_id),
    FOREIGN KEY (from_egg_id) REFERENCES eggs (id)
);

CREATE INDEX IF NOT EXISTS idx_dragons_owner ON dragons (owner_id);

-- Keep updated_at fresh whenever a player row changes.
CREATE TRIGGER IF NOT EXISTS trg_players_updated_at
AFTER UPDATE ON players
FOR EACH ROW
BEGIN
    UPDATE players SET updated_at = datetime('now') WHERE user_id = NEW.user_id;
END;

-- Random mystery chests spawned in groups.
CREATE TABLE IF NOT EXISTS chests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id      INTEGER NOT NULL,                  -- Telegram group chat ID
    message_id    INTEGER,                           -- spawn message (for button updates)
    status        TEXT NOT NULL DEFAULT 'available', -- available | opened | expired
    opened_by     INTEGER,                           -- Telegram user ID of the opener
    is_test       INTEGER NOT NULL DEFAULT 0,        -- 1 if created via the admin test tools
    created_time  REAL NOT NULL,
    opened_time   REAL,
    delete_after  REAL,                              -- when the message must be deleted (V5)
    reward        TEXT,                              -- JSON snapshot of what was granted
    FOREIGN KEY (opened_by) REFERENCES players (user_id)
);

CREATE INDEX IF NOT EXISTS idx_chests_group_status ON chests (group_id, status);
CREATE INDEX IF NOT EXISTS idx_chests_status_created ON chests (status, created_time);

-- Dragon breeding rituals (Version 9). One row per 🧬 آیین پیوند. A partial
-- unique index guarantees a dragon can only take part in one active ritual,
-- so double-tapping «تایید» can never start two.
CREATE TABLE IF NOT EXISTS breedings (
    breeding_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id     INTEGER NOT NULL,
    parent1_id   INTEGER NOT NULL,
    parent2_id   INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active',   -- active | done | cancelled
    start_time   REAL NOT NULL,
    finish_time  REAL NOT NULL,
    chat_id      INTEGER,                          -- group to announce in
    cost         INTEGER NOT NULL DEFAULT 0,       -- ✨ aether paid
    child_id     INTEGER,                          -- dragon produced
    outcome      TEXT,                             -- inherit | hybrid | mutation
    FOREIGN KEY (owner_id)   REFERENCES players (user_id),
    FOREIGN KEY (parent1_id) REFERENCES dragons (id),
    FOREIGN KEY (parent2_id) REFERENCES dragons (id)
);

CREATE INDEX IF NOT EXISTS idx_breedings_due
    ON breedings (status, finish_time);
CREATE INDEX IF NOT EXISTS idx_breedings_owner
    ON breedings (owner_id, status);

-- Arena PvP battles (Version 7). Replaces the old PvE `battles` table: every
-- row is one finished duel between two players' dragons. It is an append-only
-- history used for the result screen and stats; no "active battle" state is
-- kept because an arena fight resolves in a single call.
CREATE TABLE IF NOT EXISTS arena_battles (
    battle_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    challenger_id   INTEGER NOT NULL,              -- player who pressed "find opponent"
    opponent_id     INTEGER NOT NULL,              -- matched player
    challenger_dragon_id INTEGER NOT NULL,
    opponent_dragon_id   INTEGER NOT NULL,
    winner_id       INTEGER NOT NULL,              -- user_id of the winner
    turns           INTEGER NOT NULL DEFAULT 0,
    chat_id         INTEGER,                       -- group the duel happened in
    log             TEXT,                          -- JSON turn-by-turn log
    reward          TEXT,                          -- JSON snapshot of what was granted
    created_time    REAL NOT NULL,
    FOREIGN KEY (challenger_id) REFERENCES players (user_id),
    FOREIGN KEY (opponent_id)   REFERENCES players (user_id)
);

CREATE INDEX IF NOT EXISTS idx_arena_battles_challenger
    ON arena_battles (challenger_id, created_time);
-- NOTE: the leaderboard index on players(arena_points) is created by
-- database/migrate.py, NOT here. This file runs before the migrations, so on
-- an upgraded database the column would not exist yet and startup would fail.
