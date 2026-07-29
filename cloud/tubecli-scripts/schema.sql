-- tubecli-scripts-db — central browser-automation script store.
-- Cloned from the t2login contract, with two departures: a rollup table so
-- /api/script-stats is a single scan instead of a re-aggregation, and a raw
-- outcome log so a broken script can be traced to the step that broke it.

CREATE TABLE IF NOT EXISTS scripts (
  slug              TEXT PRIMARY KEY,
  name              TEXT NOT NULL,
  description       TEXT NOT NULL DEFAULT '',
  category          TEXT NOT NULL DEFAULT 'general',
  target_url        TEXT NOT NULL DEFAULT '',
  tags              TEXT NOT NULL DEFAULT '[]',   -- JSON array
  steps             TEXT NOT NULL DEFAULT '[]',   -- JSON array
  variables         TEXT NOT NULL DEFAULT '[]',   -- JSON array
  is_function       INTEGER NOT NULL DEFAULT 0,
  function_inputs   TEXT NOT NULL DEFAULT '[]',   -- JSON array
  function_outputs  TEXT NOT NULL DEFAULT '[]',   -- JSON array
  engine            TEXT NOT NULL DEFAULT 'any',  -- any | shardx | bas
  min_client        TEXT NOT NULL DEFAULT '',
  enabled           INTEGER NOT NULL DEFAULT 1,
  created_at        TEXT NOT NULL DEFAULT '',
  updated_at        TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_scripts_updated  ON scripts(updated_at);
CREATE INDEX IF NOT EXISTS idx_scripts_category ON scripts(category);

-- One row per run. Kept raw so the admin page can answer "which step fails".
CREATE TABLE IF NOT EXISTS script_outcomes (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  slug              TEXT NOT NULL,
  machine_id        TEXT NOT NULL DEFAULT '',
  client_version    TEXT NOT NULL DEFAULT '',
  engine            TEXT NOT NULL DEFAULT '',
  success           INTEGER NOT NULL,
  failed_step_index INTEGER,
  failed_step_label TEXT NOT NULL DEFAULT '',
  error             TEXT NOT NULL DEFAULT '',
  duration_ms       INTEGER,
  created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_outcomes_slug_time ON script_outcomes(slug, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_outcomes_time      ON script_outcomes(created_at DESC);

-- Rollup: the numbers the client and the dashboard read.
--
-- seed_* holds history migrated from t2login, which this store never witnessed
-- and has no raw rows for. It is kept apart from attempts/successes so that
-- rebuilding the rollup from script_outcomes ADDS to the inherited baseline
-- instead of replacing it — otherwise the first real run of a migrated script
-- would reduce "114/196" to "0/1" and destroy the only copy of that history.
CREATE TABLE IF NOT EXISTS script_stats (
  slug            TEXT PRIMARY KEY,
  attempts        INTEGER NOT NULL DEFAULT 0,
  successes       INTEGER NOT NULL DEFAULT 0,
  last_success_at TEXT NOT NULL DEFAULT '',
  last_failure_at TEXT NOT NULL DEFAULT '',
  last_error      TEXT NOT NULL DEFAULT '',
  seed_attempts   INTEGER NOT NULL DEFAULT 0,
  seed_successes  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS clients (
  machine_id  TEXT PRIMARY KEY,
  hostname    TEXT NOT NULL DEFAULT '',
  version     TEXT NOT NULL DEFAULT '',
  platform    TEXT NOT NULL DEFAULT '',
  first_seen  TEXT NOT NULL DEFAULT '',
  last_seen   TEXT NOT NULL DEFAULT '',
  runs        INTEGER NOT NULL DEFAULT 0
);
