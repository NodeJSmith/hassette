-- Migration 012: listeners.event_priority
-- Records the priority tier resolved at registration (explicit event_priority= or the
-- topic-derived default). Existing rows backfill to 'normal', which is also the tier the
-- classifier assigns to every topic it does not recognize.

ALTER TABLE listeners ADD COLUMN event_priority TEXT NOT NULL DEFAULT 'normal'
    CHECK (event_priority IN ('low', 'normal', 'high', 'critical'));
