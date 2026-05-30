-- Migration 001: unified schema
-- Replaces the 10-migration Alembic chain with a single clean schema.
-- auto_vacuum = INCREMENTAL is set by the migration runner before this file runs.

-- sessions
CREATE TABLE sessions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at            REAL    NOT NULL,
    stopped_at            REAL,
    last_heartbeat_at     REAL    NOT NULL,
    status                TEXT    NOT NULL
        CHECK (status IN ('running', 'stopped', 'crashed', 'success', 'failure', 'unknown')),
    error_type            TEXT,
    error_message         TEXT,
    error_traceback       TEXT,
    dropped_overflow      INTEGER NOT NULL DEFAULT 0,
    dropped_exhausted     INTEGER NOT NULL DEFAULT 0,
    dropped_shutdown      INTEGER NOT NULL DEFAULT 0
);

-- listeners
-- Natural key: (app_key, instance_index, name, topic)
-- name is NOT NULL. handler_method stays as display-only metadata.
CREATE TABLE listeners (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT    NOT NULL,
    instance_index        INTEGER NOT NULL,
    name                  TEXT    NOT NULL,
    handler_method        TEXT    NOT NULL,
    topic                 TEXT    NOT NULL,
    debounce              REAL,
    throttle              REAL,
    once                  INTEGER NOT NULL DEFAULT 0,
    priority              INTEGER NOT NULL DEFAULT 0,
    immediate             INTEGER NOT NULL DEFAULT 0,
    duration              REAL,
    entity_id             TEXT,
    predicate_description TEXT,
    human_description     TEXT,
    source_location       TEXT    NOT NULL,
    registration_source   TEXT,
    retired_at            REAL,
    source_tier           TEXT    NOT NULL DEFAULT 'app'
        CHECK (source_tier IN ('app', 'framework')),
    CHECK ((app_key != '__hassette__' AND app_key NOT GLOB '__hassette__.*') OR source_tier = 'framework')
);

CREATE INDEX idx_listeners_app ON listeners(app_key, instance_index);
CREATE UNIQUE INDEX idx_listeners_natural
    ON listeners(app_key, instance_index, name, topic);

-- scheduled_jobs (natural key unchanged: app_key, instance_index, job_name)
CREATE TABLE scheduled_jobs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT    NOT NULL,
    instance_index        INTEGER NOT NULL,
    job_name              TEXT    NOT NULL,
    handler_method        TEXT    NOT NULL,
    trigger_type          TEXT
        CHECK (trigger_type IN ('interval', 'cron', 'once', 'after', 'custom')),
    trigger_label         TEXT    NOT NULL DEFAULT '',
    trigger_detail        TEXT,
    repeat                INTEGER NOT NULL DEFAULT 0,
    args_json             TEXT    NOT NULL DEFAULT '[]',
    kwargs_json           TEXT    NOT NULL DEFAULT '{}',
    source_location       TEXT    NOT NULL,
    registration_source   TEXT,
    retired_at            REAL,
    source_tier           TEXT    NOT NULL DEFAULT 'app'
        CHECK (source_tier IN ('app', 'framework')),
    "group"               TEXT,
    cancelled_at          REAL,
    name_auto             INTEGER NOT NULL DEFAULT 0,
    CHECK ((app_key != '__hassette__' AND app_key NOT GLOB '__hassette__.*') OR source_tier = 'framework')
);

CREATE INDEX idx_scheduled_jobs_app ON scheduled_jobs(app_key, instance_index);
CREATE UNIQUE INDEX idx_scheduled_jobs_natural
    ON scheduled_jobs(app_key, instance_index, job_name);

-- executions: unified table replacing handler_invocations + job_executions
CREATE TABLE executions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                  TEXT    NOT NULL CHECK (kind IN ('handler', 'job')),
    listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
    job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
    session_id            INTEGER NOT NULL REFERENCES sessions(id),
    execution_start_ts    REAL    NOT NULL,
    duration_ms           REAL    NOT NULL
        CHECK (duration_ms >= 0.0),
    status                TEXT    NOT NULL
        CHECK (status IN ('success', 'error', 'cancelled', 'timed_out')),
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
    CHECK ((listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1)
);

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

-- log_records (unchanged from migration 009)
CREATE TABLE log_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    seq             INTEGER NOT NULL,
    timestamp       REAL    NOT NULL,
    level           TEXT    NOT NULL,
    logger_name     TEXT    NOT NULL,
    func_name       TEXT,
    lineno          INTEGER,
    message         TEXT    NOT NULL,
    exc_info        TEXT,
    app_key         TEXT,
    instance_name   TEXT,
    instance_index  INTEGER,
    execution_id    TEXT,
    source_tier     TEXT
);

CREATE INDEX idx_lr_time     ON log_records(timestamp);
CREATE INDEX idx_lr_exec     ON log_records(execution_id) WHERE execution_id IS NOT NULL;
CREATE INDEX idx_lr_app_time ON log_records(app_key, timestamp);

-- Views
CREATE VIEW active_app_listeners AS
    SELECT * FROM listeners WHERE retired_at IS NULL AND source_tier = 'app';
CREATE VIEW active_framework_listeners AS
    SELECT * FROM listeners WHERE retired_at IS NULL AND source_tier = 'framework';
CREATE VIEW active_listeners AS
    SELECT * FROM listeners WHERE retired_at IS NULL;

CREATE VIEW active_app_scheduled_jobs AS
    SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND source_tier = 'app';
CREATE VIEW active_framework_scheduled_jobs AS
    SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND source_tier = 'framework';
CREATE VIEW active_scheduled_jobs AS
    SELECT * FROM scheduled_jobs WHERE retired_at IS NULL;
