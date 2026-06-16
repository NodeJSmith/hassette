-- Migration 007: blocking_events.reason — finer-grained attribution outcome.
-- Splits the overloaded NULL app_key into "framework" (no execution was bound) vs
-- "displaced" (an execution was bound but it was not the task frozen on the loop, so
-- attribution was withheld rather than guessed). "attributed" means app_key is trusted.
-- Nullable: rows written before this migration keep NULL.
ALTER TABLE blocking_events ADD COLUMN reason TEXT
    CHECK (reason IN ('attributed', 'framework', 'displaced'));
