-- Dubai Hunt — SQLite schema
-- A single .db file at db/dubai_hunt.db is the canonical source of truth.
-- Scrapers UPSERT (no overwrites). Frontends + bot + API all read from here.

PRAGMA journal_mode = WAL;     -- concurrent reads while writer is active
PRAGMA foreign_keys = ON;

-- ── cars ───────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cars (
    ad_id          TEXT PRIMARY KEY,             -- e.g. "dubizzle_<uuid>"
    source         TEXT NOT NULL,                 -- Dubizzle | DubiCars | YallaMotor | CarSwitch
    title          TEXT,
    brand          TEXT,                          -- canonical "Honda Civic"
    year           INTEGER,
    km             INTEGER,
    price_aed      INTEGER,
    transmission   TEXT,
    trim           TEXT,
    color          TEXT,
    body_type      TEXT,
    fuel           TEXT,
    seller_type    TEXT,                          -- "OW"|"DL"|""
    location       TEXT,
    has_sunroof    INTEGER NOT NULL DEFAULT 0,    -- 0/1
    features       TEXT,                          -- pipe-separated
    description    TEXT,
    image          TEXT,
    url            TEXT,
    scraped_at     TEXT,                          -- ISO timestamp last seen
    first_seen_at  TEXT,                          -- ISO timestamp first inserted
    is_active      INTEGER NOT NULL DEFAULT 1     -- 0 if removed in latest run
);
CREATE INDEX IF NOT EXISTS ix_cars_price  ON cars(price_aed);
CREATE INDEX IF NOT EXISTS ix_cars_brand  ON cars(brand);
CREATE INDEX IF NOT EXISTS ix_cars_sun    ON cars(has_sunroof);
CREATE INDEX IF NOT EXISTS ix_cars_active ON cars(is_active);

-- ── apartments ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS apartments (
    ad_id           TEXT PRIMARY KEY,             -- "bayut_<id>" | "pf_<id>"
    source          TEXT NOT NULL,
    title           TEXT,
    price_aed       INTEGER NOT NULL,             -- yearly
    monthly_aed     INTEGER NOT NULL,             -- = price_aed / 12
    bedrooms        INTEGER,
    bathrooms       INTEGER,
    size_sqft       INTEGER,
    area            TEXT,                         -- canonical short label
    commute_tier    INTEGER,                      -- 1..4 (lower = closer to DAFZA)
    full_location   TEXT,
    furnished       INTEGER NOT NULL DEFAULT 1,
    amenities       TEXT,                         -- pipe-separated
    image           TEXT,
    url             TEXT,
    broker          TEXT,
    agent_name      TEXT,
    agent_phone     TEXT,
    lat             REAL,
    lon             REAL,
    description     TEXT,
    scraped_at      TEXT,
    first_seen_at   TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_apt_monthly ON apartments(monthly_aed);
CREATE INDEX IF NOT EXISTS ix_apt_tier    ON apartments(commute_tier);
CREATE INDEX IF NOT EXISTS ix_apt_area    ON apartments(area);
CREATE INDEX IF NOT EXISTS ix_apt_active  ON apartments(is_active);

-- ── scrape_runs (audit log) ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scrape_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,                  -- 'cars' | 'apartments'
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    rows_seen    INTEGER DEFAULT 0,              -- rows we encountered this run
    rows_new     INTEGER DEFAULT 0,              -- inserted
    rows_updated INTEGER DEFAULT 0,
    notes        TEXT
);

-- ── meta (key/value) ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
