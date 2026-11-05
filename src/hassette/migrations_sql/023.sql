-- Migration 023: event summary for handler executions.
--
-- Records which event, entity and value change fired a handler run, next to the existing
-- trigger_context_id and trigger_origin. All nullable with no backfill: job rows and rows written
-- before this migration leave them NULL. trigger_old_value/trigger_new_value hold display strings
-- capped in core/execution_record_builder.py (TRIGGER_VALUE_MAX_CHARS), not typed JSON.
ALTER TABLE executions ADD COLUMN trigger_topic TEXT;
ALTER TABLE executions ADD COLUMN trigger_entity_id TEXT;
ALTER TABLE executions ADD COLUMN trigger_old_value TEXT;
ALTER TABLE executions ADD COLUMN trigger_new_value TEXT;
ALTER TABLE executions ADD COLUMN trigger_parent_id TEXT;
