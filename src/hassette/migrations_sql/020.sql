-- Migration 020: drop instance_index; the instance name is the only instance identity.
--
-- The stored values were written at registration or log time, so a config reorder left them stale, and nothing
-- reads them now. Display order comes from the list position of AppSummary.instances. No index, view or trigger
-- names these columns (018 dropped the last index), so each drop only rewrites its table.
--
-- One-way: rolling back past 020 means deleting the telemetry database, as with 018.
ALTER TABLE log_records DROP COLUMN instance_index;
ALTER TABLE blocking_events DROP COLUMN instance_index;
ALTER TABLE listeners DROP COLUMN instance_index;
ALTER TABLE scheduled_jobs DROP COLUMN instance_index;
