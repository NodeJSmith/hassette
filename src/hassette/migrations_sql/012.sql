-- Migration 012: registered manual jobs -- removal terminology and schedule status.
--
-- Renames cancelled_at -> removed_at on both listeners and scheduled_jobs. Removal replaces
-- cancellation for registration lifecycle (cancellation remains only for interrupted
-- execution): both columns already meant "registration removed", this is a terminology
-- correction, not a behavioral change.
--
-- Extends scheduled_jobs.trigger_type to allow 'manual' (Scheduler.register() with no
-- trigger) and adds schedule_status/schedule_status_reason to persist the four-value
-- Job.ScheduleStatus state machine durably.
--
-- This is the first migration in the project's history to rebuild an FK-parent table:
-- executions.job_id REFERENCES scheduled_jobs(id) ON DELETE SET NULL. SQLite does not
-- enforce foreign keys during migration (migration_runner uses a bare sqlite3.connect()
-- with no PRAGMA foreign_keys), so DROP TABLE scheduled_jobs below does not cascade or
-- null out executions.job_id -- but the rebuild's INSERT...SELECT must still explicitly
-- enumerate and preserve `id` so every existing executions.job_id continues to resolve
-- once the new table is renamed into place.

-- Part A: listeners.cancelled_at -> removed_at. Plain RENAME COLUMN -- listeners is not an
-- FK-parent whose id continuity matters here, and no index/CHECK/view references the column
-- by name, so no rebuild is needed.
ALTER TABLE listeners RENAME COLUMN cancelled_at TO removed_at;

-- Part B: scheduled_jobs rebuild. SQLite has no ALTER CONSTRAINT and ALTER TABLE ADD COLUMN
-- cannot add a NOT NULL column without a DEFAULT, so the table is rebuilt: create the new
-- schema, copy every row (enumerating `id` explicitly to preserve FK targets), drop the old
-- table, rename the new one into place, then recreate every index.
--
-- The views over scheduled_jobs/listeners must be dropped BEFORE the DROP TABLE below --
-- SQLite eagerly revalidates dependent views when the underlying table's schema changes, and
-- a DROP TABLE with a live view still referencing it by name fails with
-- "no such table: main.scheduled_jobs".
DROP VIEW active_app_listeners;
DROP VIEW active_framework_listeners;
DROP VIEW active_listeners;
DROP VIEW active_app_scheduled_jobs;
DROP VIEW active_framework_scheduled_jobs;
DROP VIEW active_scheduled_jobs;

CREATE TABLE scheduled_jobs_new (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key                 TEXT    NOT NULL,
    instance_index          INTEGER NOT NULL,
    job_name                TEXT    NOT NULL,
    handler_method          TEXT    NOT NULL,
    trigger_type            TEXT
        CHECK (trigger_type IN ('interval', 'cron', 'once', 'after', 'custom', 'manual')),
    trigger_label           TEXT    NOT NULL DEFAULT '',
    trigger_detail          TEXT,
    repeat                  INTEGER NOT NULL DEFAULT 0,
    args_json               TEXT    NOT NULL DEFAULT '[]',
    kwargs_json             TEXT    NOT NULL DEFAULT '{}',
    source_location         TEXT    NOT NULL,
    registration_source     TEXT,
    retired_at              REAL,
    source_tier             TEXT    NOT NULL DEFAULT 'app'
        CHECK (source_tier IN ('app', 'framework')),
    "group"                 TEXT,
    removed_at              REAL,
    mode                    TEXT    NOT NULL DEFAULT 'single'
        CHECK (mode IN ('single', 'restart', 'queued', 'parallel')),
    predicate_description   TEXT,
    human_description       TEXT,
    schedule_status         TEXT    NOT NULL
        CHECK (schedule_status IN ('scheduled', 'waiting', 'completed', 'manual')),
    schedule_status_reason  TEXT
        CHECK (schedule_status_reason IN ('legacy_unknown', 'trigger_error') OR schedule_status_reason IS NULL),
    CHECK ((app_key != '__hassette__' AND app_key NOT GLOB '__hassette__.*') OR source_tier = 'framework')
);

-- Legacy rows cannot be assigned a truthful schedule state -- the old schema never stored
-- heap state. Backfill schedule_status='scheduled' with schedule_status_reason='legacy_unknown'
-- so every consumer treats the placeholder status as unknown rather than a real guarantee.
-- Runtime re-registration overwrites both fields via the ON CONFLICT DO UPDATE upsert before
-- app startup completes.
INSERT INTO scheduled_jobs_new (
    id, app_key, instance_index, job_name, handler_method,
    trigger_type, trigger_label, trigger_detail, repeat,
    args_json, kwargs_json, source_location, registration_source,
    retired_at, source_tier, "group", removed_at, mode,
    predicate_description, human_description,
    schedule_status, schedule_status_reason
)
SELECT
    id, app_key, instance_index, job_name, handler_method,
    trigger_type, trigger_label, trigger_detail, repeat,
    args_json, kwargs_json, source_location, registration_source,
    retired_at, source_tier, "group", cancelled_at, mode,
    predicate_description, human_description,
    'scheduled', 'legacy_unknown'
FROM scheduled_jobs;

DROP TABLE scheduled_jobs;
ALTER TABLE scheduled_jobs_new RENAME TO scheduled_jobs;

CREATE INDEX idx_scheduled_jobs_app ON scheduled_jobs(app_key, instance_index);
CREATE UNIQUE INDEX idx_scheduled_jobs_natural
    ON scheduled_jobs(app_key, instance_index, job_name);

-- Part C: recreate the active_* views for both tables. They previously filtered only on
-- retired_at IS NULL; removed_at is a distinct lifecycle marker (explicit runtime removal vs.
-- startup-time reconciliation) and either can leave a stale row active, so both must be
-- filtered.
CREATE VIEW active_app_listeners AS
    SELECT * FROM listeners WHERE retired_at IS NULL AND removed_at IS NULL AND source_tier = 'app';
CREATE VIEW active_framework_listeners AS
    SELECT * FROM listeners WHERE retired_at IS NULL AND removed_at IS NULL AND source_tier = 'framework';
CREATE VIEW active_listeners AS
    SELECT * FROM listeners WHERE retired_at IS NULL AND removed_at IS NULL;

CREATE VIEW active_app_scheduled_jobs AS
    SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND removed_at IS NULL AND source_tier = 'app';
CREATE VIEW active_framework_scheduled_jobs AS
    SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND removed_at IS NULL AND source_tier = 'framework';
CREATE VIEW active_scheduled_jobs AS
    SELECT * FROM scheduled_jobs WHERE retired_at IS NULL AND removed_at IS NULL;
