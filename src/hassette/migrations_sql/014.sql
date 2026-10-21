-- Migration 014: drop app_manifests.auto_loaded.
-- App autodetection is gone: every app comes from an explicit config entry, so the column would
-- always be 0. It has no index, view, or foreign key, so a plain DROP COLUMN suffices.
ALTER TABLE app_manifests DROP COLUMN auto_loaded;
