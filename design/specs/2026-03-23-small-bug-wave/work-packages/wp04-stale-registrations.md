# WP04: Stale registration cleanup at startup (#380)

**Lane:** todo
**Closes:** #380

## Summary

Delete stale listener and scheduled job rows from the telemetry DB at app startup time (before re-registration). Add a migration to make FK columns nullable with `ON DELETE SET NULL` so parent rows can be deleted without losing invocation/execution history. Fix INNER JOINs in telemetry queries to handle orphaned rows.

## Acceptance Criteria

- [ ] Migration 003 makes `handler_invocations.listener_id` and `job_executions.job_id` nullable with `ON DELETE SET NULL`
- [ ] Migration uses `batch_alter_table` (SQLite cannot ALTER column constraints in-place)
- [ ] `clear_registrations(app_key)` DELETEs from `listeners` and `scheduled_jobs` WHERE `app_key = ?`
- [ ] `start_app()` calls `clear_registrations()` before `initialize_instances()`
- [ ] After app reload, only currently-registered listeners/jobs appear in telemetry
- [ ] Orphaned invocation/execution history rows (with NULL parent ID) remain visible in error feeds
- [ ] INNER JOINs in `get_recent_errors` and `get_slow_handlers` changed to LEFT JOIN

## Files to Change

| File | Change |
|------|--------|
| `src/hassette/migrations/versions/003_nullable_fk_for_cleanup.py` | New migration using `batch_alter_table` for both tables |
| `src/hassette/core/command_executor.py` | Add `clear_registrations(app_key)` method |
| `src/hassette/core/app_lifecycle_service.py` | Call `clear_registrations()` in `start_app()` before `initialize_instances()` |
| `src/hassette/core/telemetry_query_service.py` | Change INNER JOINs to LEFT JOIN in `get_recent_errors` (~lines 397, 414) and `get_slow_handlers` (~line 480) |

## Migration Pattern

Follow the existing pattern in migration 002 (`batch_alter_table`):

```python
revision = "003"
down_revision = "002"

def upgrade() -> None:
    with op.batch_alter_table("handler_invocations") as batch_op:
        batch_op.alter_column("listener_id", existing_type=sa.Integer, nullable=True)
        # Re-create FK with ON DELETE SET NULL

    with op.batch_alter_table("job_executions") as batch_op:
        batch_op.alter_column("job_id", existing_type=sa.Integer, nullable=True)
        # Re-create FK with ON DELETE SET NULL
```

## Verification

```bash
# Run migration
uv run pytest tests/integration/test_migrations.py -v  # if exists

# Run telemetry tests
uv run pytest tests/integration/ -v -k "telemetry or listener or job"

# Manual verification: reload an app, check /api/telemetry/app/{key}/listeners shows only current handlers
```
