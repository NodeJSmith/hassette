-- Migration 013: blocking_events.frames — structured stack frames.
-- A JSON array of {filename, lineno, function, module} objects, innermost frame first: the
-- captured loop-thread stack for Tier 1 (watchdog) rows, the single caller frame for Tier 2
-- (monkeypatch) rows. NULL for rows written before this migration and for rows with no
-- captured stack. source_location keeps its text form; readers derive call sites from frames.
-- Whether a frame is user code is decided at read time, never stored.
ALTER TABLE blocking_events ADD COLUMN frames TEXT;
