ALTER TABLE listeners ADD COLUMN backpressure TEXT NOT NULL DEFAULT 'block'
    CHECK (backpressure IN ('block', 'drop_newest'));
