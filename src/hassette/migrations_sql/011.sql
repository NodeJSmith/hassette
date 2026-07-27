-- Migration 011: app_manifests table
-- Persists app manifest metadata (class name, display name, filename, enabled,
-- autostart, auto-loaded) so the web UI can show app identity without a running
-- hassette instance (seed DB workflows) and so apps removed from config remain
-- visible with their historical telemetry. Natural key: app_key (UNIQUE).
-- No session_id FK -- this is a snapshot table where every upsert overwrites in
-- place, not a history table.

CREATE TABLE IF NOT EXISTS app_manifests (
    id           INTEGER PRIMARY KEY,
    app_key      TEXT NOT NULL UNIQUE,
    class_name   TEXT NOT NULL,
    display_name TEXT NOT NULL,
    filename     TEXT NOT NULL,
    enabled      INTEGER NOT NULL DEFAULT 1,
    autostart    INTEGER NOT NULL DEFAULT 1,
    auto_loaded  INTEGER NOT NULL DEFAULT 0,
    -- format must match the upsert's `updated_at` clause in telemetry/repository.py
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
