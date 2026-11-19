-- Migration 027: integration_entities — the buttons, switches and sensors app instances declare (spec 157).
--
-- One row per declared entity, keyed by (app_key, instance_name, key, platform). A row holds both the
-- declaration and, for a switch or sensor, its last state, so removing a declaration removes its state in the
-- same delete (spec 157 D4). An instance's whole set is replaced in one transaction when it reaches running:
-- kept rows are upserted, keeping their state, and the rest are deleted (core/integration_store.py).
--
-- value is a JSON scalar: a switch's bool, or a sensor's number or string, with a timestamp as an ISO 8601
-- string with offset and a date as an ISO 8601 date. NULL is a sensor's unknown and a button's (stateless) value.
-- A switch's initial is written into value when its row is first inserted. attributes is a JSON object, or NULL
-- for a button. options is a JSON array, for an enum sensor only.
--
-- This table holds the only copy of switch and sensor state, so it is never a retention or size-failsafe target.
CREATE TABLE integration_entities (
    app_key            TEXT NOT NULL,
    instance_name      TEXT NOT NULL,
    key                TEXT NOT NULL,
    platform           TEXT NOT NULL CHECK (platform IN ('button', 'switch', 'sensor')),
    name               TEXT NOT NULL,
    default_entity_id  TEXT,
    initial            INTEGER,
    unit               TEXT,
    device_class       TEXT,
    state_class        TEXT,
    options            TEXT,
    value              TEXT,
    attributes         TEXT,
    PRIMARY KEY (app_key, instance_name, key, platform)
);
