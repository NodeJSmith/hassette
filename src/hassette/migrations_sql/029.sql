-- Migration 029: integration_entities.icon — an icon name such as 'mdi:cat', NULL for Home Assistant's default.
--
-- Validated by the integration declarations (integration/declarations.py), so the column carries no CHECK.
ALTER TABLE integration_entities ADD COLUMN icon TEXT;
