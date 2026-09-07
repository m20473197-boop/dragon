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
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_players_username ON players (username);

-- Groups the bot is active in (used by the egg spawner).
CREATE TABLE IF NOT EXISTS chats (
    chat_id    INTEGER PRIMARY KEY,                 -- Telegram group chat ID
    title      TEXT,
    last_seen  REAL NOT NULL                        -- unix timestamp of last activity
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
    power        INTEGER NOT NULL DEFAULT 20,        -- attack power
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
