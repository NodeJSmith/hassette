-- Migration 009: scheduler where= predicate support
-- Adds predicate_description/human_description to scheduled_jobs (mirrors the
-- listeners table columns added in 001.sql) and allows 'skipped' as a valid
-- executions.status value.

-- Part A: scheduled_jobs gains predicate description columns.
ALTER TABLE scheduled_jobs ADD COLUMN predicate_description TEXT;
ALTER TABLE scheduled_jobs ADD COLUMN human_description TEXT;

-- Part B: executions.status CHECK constraint must allow 'skipped'.
-- SQLite has no ALTER CONSTRAINT — recreate the table with the updated CHECK,
-- copy all rows, drop the old table, rename, then recreate every index.
CREATE TABLE executions_new (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                  TEXT    NOT NULL CHECK (kind IN ('handler', 'job')),
    listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
    job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
    session_id            INTEGER NOT NULL REFERENCES sessions(id),
    execution_start_ts    REAL    NOT NULL,
    duration_ms           REAL    NOT NULL
        CHECK (duration_ms >= 0.0),
    status                TEXT    NOT NULL
        CHECK (status IN ('success', 'error', 'cancelled', 'timed_out', 'skipped')),
    error_type            TEXT,
    error_message         TEXT,
    error_traceback       TEXT,
    is_di_failure         INTEGER NOT NULL DEFAULT 0,
    source_tier           TEXT    NOT NULL DEFAULT 'app'
        CHECK (source_tier IN ('app', 'framework')),
    execution_id          TEXT UNIQUE,
    trigger_context_id    TEXT,
    trigger_origin        TEXT,
    trigger_mode          TEXT,
    retry_count           INTEGER NOT NULL DEFAULT 0,
    attempt_number        INTEGER NOT NULL DEFAULT 1,
    args_json             TEXT    NOT NULL DEFAULT '[]',
    kwargs_json           TEXT    NOT NULL DEFAULT '{}',
    thread_leaked         INTEGER NOT NULL DEFAULT 0,
    CHECK ((listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1)
);

INSERT INTO executions_new (
    id, kind, listener_id, job_id, session_id, execution_start_ts, duration_ms,
    status, error_type, error_message, error_traceback, is_di_failure, source_tier,
    execution_id, trigger_context_id, trigger_origin, trigger_mode, retry_count,
    attempt_number, args_json, kwargs_json, thread_leaked
)
SELECT
    id, kind, listener_id, job_id, session_id, execution_start_ts, duration_ms,
    status, error_type, error_message, error_traceback, is_di_failure, source_tier,
    execution_id, trigger_context_id, trigger_origin, trigger_mode, retry_count,
    attempt_number, args_json, kwargs_json, thread_leaked
FROM executions;

DROP TABLE executions;
ALTER TABLE executions_new RENAME TO executions;

CREATE INDEX idx_exec_listener_time
    ON executions(listener_id, execution_start_ts DESC)
    WHERE listener_id IS NOT NULL;
CREATE INDEX idx_exec_job_time
    ON executions(job_id, execution_start_ts DESC)
    WHERE job_id IS NOT NULL;
CREATE INDEX idx_exec_status_time  ON executions(status, execution_start_ts DESC);
CREATE INDEX idx_exec_time         ON executions(execution_start_ts);
CREATE INDEX idx_exec_session      ON executions(session_id);
CREATE INDEX idx_exec_source_tier_time ON executions(source_tier, execution_start_ts DESC);
