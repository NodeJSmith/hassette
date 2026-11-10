-- Migration 024: api_writes — one row per named Api write an app sent to Home Assistant.
--
-- Written as 'pending' when the write is sent and updated once its outcome is known
-- (core/api_write_recorder.py). write_id is client-generated (UUIDv7), so the update needs nothing
-- back from the insert. target is a JSON object of id lists; data is a display string capped in
-- core/api_write_recorder.py (API_WRITE_DATA_MAX_CHARS), not typed JSON.
CREATE TABLE api_writes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    write_id       TEXT NOT NULL,
    session_id     INTEGER REFERENCES sessions(id),
    app_key        TEXT NOT NULL,
    instance_name  TEXT NOT NULL,
    execution_id   TEXT,
    kind           TEXT NOT NULL
        CHECK (kind IN ('call_service', 'fire_event', 'set_state', 'delete_entity',
                        'helper_create', 'helper_update', 'helper_delete')),
    operation      TEXT,
    target         TEXT,
    data           TEXT,
    outcome        TEXT NOT NULL
        CHECK (outcome IN ('pending', 'success', 'rejected', 'connection_lost', 'unresolved', 'not_sent')),
    error_code     TEXT,
    error_message  TEXT,
    context_id     TEXT,
    sent_ts        REAL NOT NULL,
    resolved_ts    REAL
);

CREATE UNIQUE INDEX idx_aw_write_id ON api_writes(write_id);
CREATE INDEX idx_aw_execution    ON api_writes(execution_id);
CREATE INDEX idx_aw_context      ON api_writes(context_id);
CREATE INDEX idx_aw_ts           ON api_writes(sent_ts);
CREATE INDEX idx_aw_app_ts       ON api_writes(app_key, sent_ts);
CREATE INDEX idx_aw_session      ON api_writes(session_id);
-- The startup sweep (SessionManager) reads only pending rows; SQLite uses this partial index when the
-- query's WHERE implies outcome = 'pending'.
CREATE INDEX idx_aw_pending      ON api_writes(sent_ts) WHERE outcome = 'pending';
