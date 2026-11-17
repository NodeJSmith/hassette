-- Migration 026: lifecycle_events — append-only history of app status, connection state and block changes.
--
-- One row per change, written best-effort through the database write queue (core/telemetry/lifecycle_rows.py).
-- kind names the source: 'app' rows carry app_key and instance_name, 'connection' rows neither, 'block' rows
-- app_key only. from_status is the owner's previous state and is NULL only on block rows. details is a JSON
-- object whose keys each kind's details model in core/telemetry/lifecycle_rows.py defines; models change only
-- by adding optional fields, so it carries no version key.
--
-- id is the sequence key: rows enter one FIFO write queue at the moment of change, so ordering by id within a
-- session is exact. ts is wall-clock time for display and time-window filtering only, since it can tie or step
-- back. Like the other session child tables, session_id has no ON DELETE clause: the retention session delete
-- guards it (core/database_retention.py).
CREATE TABLE lifecycle_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     INTEGER NOT NULL REFERENCES sessions(id),
    kind           TEXT NOT NULL CHECK (kind IN ('app', 'connection', 'block')),
    app_key        TEXT,
    instance_name  TEXT,
    from_status    TEXT,
    to_status      TEXT NOT NULL,
    details        TEXT NOT NULL,
    ts             REAL NOT NULL
);

CREATE INDEX idx_le_ts      ON lifecycle_events(ts);
CREATE INDEX idx_le_app_ts  ON lifecycle_events(app_key, ts);
CREATE INDEX idx_le_session ON lifecycle_events(session_id);
