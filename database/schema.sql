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
    reward        TEXT,                              -- JSON snapshot of what was granted
    FOREIGN KEY (opened_by) REFERENCES players (user_id)
);

CREATE INDEX IF NOT EXISTS idx_chests_group_status ON chests (group_id, status);
CREATE INDEX IF NOT EXISTS idx_chests_status_created ON chests (status, created_time);

-- PvE battles (Version 4). One active battle per user at a time; the row
-- survives a restart so a fight can be resumed.
CREATE TABLE IF NOT EXISTS battles (
    battle_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,                  -- owner/controller of the battle
    dragon_id     INTEGER NOT NULL,                  -- the fighting dragon
    chat_id       INTEGER,                           -- group the battle happens in
    message_id    INTEGER,                           -- battle message (for button updates)
    enemy_id      TEXT NOT NULL,                     -- key from config.ENEMIES
    enemy_hp      INTEGER NOT NULL,
    enemy_max_hp  INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',    -- active | won | lost | fled
    turns         INTEGER NOT NULL DEFAULT 0,
    created_time  REAL NOT NULL,
    updated_time  REAL,
    finished_time REAL,
    reward        TEXT,                              -- JSON snapshot of what was granted
    FOREIGN KEY (user_id)   REFERENCES players (user_id),
    FOREIGN KEY (dragon_id) REFERENCES dragons (id)
);

-- At most ONE active battle per user (enforced by the database itself).
CREATE UNIQUE INDEX IF NOT EXISTS idx_battles_one_active
    ON battles (user_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_battles_status_created ON battles (status, created_time);
