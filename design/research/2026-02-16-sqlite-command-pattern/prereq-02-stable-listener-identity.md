# Prereq 2: Stable Listener Identity Scheme

**Status**: Superseded by [Prereq 1: Design the Full Data Model](./prereq-01-data-model.md)

**Parent**: [SQLite + Command Executor research](./research.md)

Parent tables with natural key columns (`app_key`, `instance_index`, `handler_method`, `topic`) provide cross-restart identity directly. The `stable_key` composite string is no longer needed.
