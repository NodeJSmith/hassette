-- Migration 005: blocking_events table
-- Records every detected blocking event from Tier 1 (watchdog) and Tier 2 (monkeypatch).

CREATE TABLE blocking_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       INTEGER REFERENCES sessions(id),
    app_key          TEXT,
    instance_name    TEXT,
    instance_index   INTEGER,
    execution_id     TEXT,
    tier             TEXT NOT NULL
        CHECK (tier IN ('watchdog', 'monkeypatch')),
    primitive        TEXT,
    -- source_location format differs by tier (check the `tier` column before parsing):
    --   tier='monkeypatch' (Tier 2): "<file>:<lineno>" of the first non-hassette caller frame.
    --   tier='watchdog'   (Tier 1): a multi-line loop-thread stack snapshot (or NULL when none).
    source_location  TEXT,
    stall_duration_ms REAL,
    detected_ts      REAL NOT NULL,
    source_tier      TEXT NOT NULL
        CHECK (source_tier IN ('app', 'framework'))
);

CREATE INDEX idx_be_ts      ON blocking_events(detected_ts);
CREATE INDEX idx_be_app_ts  ON blocking_events(app_key, detected_ts);
CREATE INDEX idx_be_session ON blocking_events(session_id);
