---
task_id: "T15h"
title: "Update database service and schema-validation tests"
status: "done"
depends_on: ["T02", "T08"]
implements: ["AC#1"]
---

## Summary
The migration runner (T02) replaced Alembic with a PRAGMA `user_version` runner and `001.sql` defines the unified `executions` table. The database-service, migration-validation, and schema-structure tests still reference the old two-table schema and Alembic-era expectations.

## Prompt
**Files (write targets):** `tests/integration/database/test_database_service.py`, `tests/integration/database/test_database_service_migrations.py`, `tests/unit/test_schema_migration.py`, `tests/unit/core/conftest.py`.

1. `test_database_service.py`: update retention/cleanup table references from `handler_invocations`/`job_executions` to `executions`; fix any test that was red since T02.
2. `test_database_service_migrations.py`: validate the new PRAGMA `user_version` runner and `001.sql` ordering/content (not Alembic revisions).
3. `tests/unit/test_schema_migration.py`: update expected table/column names to the unified schema (table `executions` with `kind`, `listener_id`, `job_id`, FK-mutex CHECK, `idx_listeners_natural`).
4. `tests/unit/core/conftest.py`: update any inline `CREATE TABLE` statements used to build the test DB to match `001.sql`.

## Focus
- Read `src/hassette/migrations_sql/001.sql` and `src/hassette/core/migration_runner.py` as the source of truth for expected schema and migration behavior.
- Gate command: `tests/integration/database/test_database_service.py tests/integration/database/test_database_service_migrations.py tests/unit/test_schema_migration.py`.

## Verify
- [ ] Schema-validation test asserts the unified `executions` table and FK-mutex CHECK
- [ ] Migration test validates the PRAGMA user_version runner against `001.sql`
- [ ] All listed files collect and pass
