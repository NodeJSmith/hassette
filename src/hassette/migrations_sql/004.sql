ALTER TABLE scheduled_jobs ADD COLUMN mode TEXT NOT NULL DEFAULT 'single'
    CHECK (mode IN ('single', 'restart', 'queued', 'parallel'));
