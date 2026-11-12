-- Migration 025: listener_misses — hourly rollups of events that reached an app listener and didn't run it.
--
-- One row per listener, hour, reason and failing filter (core/listener_miss_recorder.py). The upsert adds
-- count, keeps the earliest first_ts, and replaces the last-event columns with a newer rollup's, so a restart
-- within the hour adds to its row. filter is '' for every reason but 'filter': the unique index includes it,
-- and SQLite treats NULLs as distinct there. The trigger_* columns match executions' (display strings).
-- Rows go with their listener (ON DELETE CASCADE).
CREATE TABLE listener_misses (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    listener_id        INTEGER NOT NULL REFERENCES listeners(id) ON DELETE CASCADE,
    hour_ts            REAL NOT NULL,
    reason             TEXT NOT NULL
        CHECK (reason IN ('filter', 'throttled', 'debounce_superseded', 'once_spent', 'busy', 'queue_full',
                          'backpressure', 'hold_cancelled', 'hold_recheck_failed',
                          'hold_entity_missing')),
    filter             TEXT NOT NULL DEFAULT '',
    count              INTEGER NOT NULL,
    first_ts           REAL NOT NULL,
    last_ts            REAL NOT NULL,
    trigger_topic      TEXT,
    trigger_entity_id  TEXT,
    trigger_old_value  TEXT,
    trigger_new_value  TEXT,
    trigger_context_id TEXT,
    trigger_parent_id  TEXT,
    trigger_origin     TEXT
);

CREATE UNIQUE INDEX idx_lm_key            ON listener_misses(listener_id, hour_ts, reason, filter);
CREATE INDEX idx_lm_listener_last         ON listener_misses(listener_id, last_ts);
CREATE INDEX idx_lm_last_ts               ON listener_misses(last_ts);
