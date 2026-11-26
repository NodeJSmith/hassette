-- Migration 028: integration_entities.entity_category — 'config' or 'diagnostic', NULL for a primary entity.
--
-- Validated by the integration declarations (integration/declarations.py), so the column carries no CHECK.
ALTER TABLE integration_entities ADD COLUMN entity_category TEXT;
