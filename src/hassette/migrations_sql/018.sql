-- Migration 018: key listeners and scheduled_jobs by instance name instead of instance index.
--
-- The index is an instance's position in config, so reordering or inserting a block moved history to a
-- different instance. The name is the instance's identity; instance_index stays as a display value.
--
-- Pre-migration rows can't be attributed to a name, so there is no backfill and upgrading resets
-- per-instance views. App-tier rows are retired under a placeholder and stay queryable by id until retention
-- removes them. The index stays in the placeholder because sibling instances can share a listener name and
-- topic, and those rows would otherwise collide under the new unique index. Framework resources have one
-- instance each and aren't changing identity, so their rows are named in place and keep their history.
--
-- Every value written here is impossible for a real instance name, whose charset excludes a leading '_'
-- (instance_name_reason in hassette/config/classes.py). No row holds the '__unset__' default after this
-- migration: it exists because SQLite needs a default to add a NOT NULL column, and the inserts always name
-- the column.
--
-- The columns are added in place, never rebuilt, so executions keep their foreign keys.
-- One-way: rolling back past 018 means deleting the telemetry database.
ALTER TABLE listeners ADD COLUMN instance_name TEXT NOT NULL DEFAULT '__unset__';
ALTER TABLE scheduled_jobs ADD COLUMN instance_name TEXT NOT NULL DEFAULT '__unset__';

UPDATE listeners SET instance_name = '__hassette__' WHERE source_tier = 'framework';
UPDATE scheduled_jobs SET instance_name = '__hassette__' WHERE source_tier = 'framework';

UPDATE listeners
SET instance_name = '__legacy__.' || instance_index,
    retired_at = COALESCE(retired_at, CAST(strftime('%s', 'now') AS REAL))
WHERE source_tier = 'app';
UPDATE scheduled_jobs
SET instance_name = '__legacy__.' || instance_index,
    retired_at = COALESCE(retired_at, CAST(strftime('%s', 'now') AS REAL))
WHERE source_tier = 'app';

DROP INDEX idx_listeners_natural;
DROP INDEX idx_listeners_app;
CREATE UNIQUE INDEX idx_listeners_natural ON listeners(app_key, instance_name, name, topic);
CREATE INDEX idx_listeners_app ON listeners(app_key, instance_name);

DROP INDEX idx_scheduled_jobs_natural;
DROP INDEX idx_scheduled_jobs_app;
CREATE UNIQUE INDEX idx_scheduled_jobs_natural ON scheduled_jobs(app_key, instance_name, job_name);
CREATE INDEX idx_scheduled_jobs_app ON scheduled_jobs(app_key, instance_name);
