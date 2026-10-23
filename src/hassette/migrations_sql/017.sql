-- Migration 017: persist scheduled job timing on scheduled_jobs.
--
-- next_run and fire_at are epoch seconds (ZonedDateTime.timestamp()); jitter is the configured upper
-- bound in seconds. All three are nullable: a waiting, completed, or manual-only job has no next
-- occurrence, and a job without jitter stores NULL. Registration writes them; existing rows stay
-- NULL until their job registers again.
ALTER TABLE scheduled_jobs ADD COLUMN next_run REAL;
ALTER TABLE scheduled_jobs ADD COLUMN fire_at REAL;
ALTER TABLE scheduled_jobs ADD COLUMN jitter REAL;
