-- Migration 019: rewrite log_records rows stored at a non-standard level.
--
-- The handler stored record.levelname unfiltered, so a custom level such as TRACE or SUCCESS reached a
-- column the web API validates against the five standard names, and one such row failed the whole response.
-- LogPersistenceHandler now normalizes the level from the record's number, which these rows no longer carry,
-- so they all become INFO.
--
-- One-way: the original level names are not kept.
UPDATE log_records SET level = 'INFO' WHERE level NOT IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL');
