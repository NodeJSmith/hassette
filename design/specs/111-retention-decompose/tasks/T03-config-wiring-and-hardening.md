---
task_id: "T03"
title: "Wire orphaned config fields, harden rollback error handling, fill test coverage gaps"
status: "done"
depends_on: ["T01", "T02"]
implements: ["FR#6", "FR#7", "FR#8", "FR#9", "AC#4", "AC#6", "AC#7", "AC#8", "AC#9"]
---

## Target Files

- modify: `src/hassette/core/database_service.py`
- modify: `tests/unit/core/test_database_service.py`
- modify: `tests/integration/database/test_database_service.py`

## Prompt

Read `design/specs/111-retention-decompose/tasks/context.md` and `design/specs/111-retention-decompose/design.md` first.

Read `src/hassette/core/database_service.py` — focus on:
- Module-level constants (lines ~31-49): `_HEARTBEAT_INTERVAL_SECONDS`, `_RETENTION_INTERVAL_SECONDS`, `_SIZE_FAILSAFE_INTERVAL_SECONDS`, `_SIZE_FAILSAFE_MAX_ITERATIONS`, `_SIZE_FAILSAFE_DELETE_BATCH`, `_SIZE_FAILSAFE_VACUUM_PAGES`, `_MAX_CONSECUTIVE_HEARTBEAT_FAILURES`
- `serve()` loop (line ~341) where these constants are referenced
- `_do_run_retention_cleanup` except block (line ~827) and `_insert_log_records` except block (line ~939)
- `run_size_failsafe()` (line ~919)

Read `src/hassette/config/models.py` — find the `DatabaseConfig` class and confirm the corresponding fields exist: `heartbeat_interval_seconds`, `retention_interval_seconds`, `size_failsafe_interval_seconds`, `size_failsafe_max_iterations`, `size_failsafe_delete_batch`, `size_failsafe_vacuum_pages`, `max_consecutive_heartbeat_failures`.

### Step 1: Wire config fields (FR#6)

Replace each module-level constant usage with a read from `self.hassette.config.database.<field>`. The constants should be removed entirely. Where the constant is used in a method that has access to `self`, read from config directly. Where it's used in a context without `self` (e.g., a module-level function), pass the value as a parameter from the calling method.

Key sites:
- `serve()`: `_HEARTBEAT_INTERVAL_SECONDS` → `self.hassette.config.database.heartbeat_interval_seconds`, same for `_RETENTION_INTERVAL_SECONDS` and `_SIZE_FAILSAFE_INTERVAL_SECONDS`
- `_check_size_failsafe` (after T02's refactoring): `_SIZE_FAILSAFE_DELETE_BATCH`, `_SIZE_FAILSAFE_MAX_ITERATIONS` → pass from caller
- `_run_failsafe_tier` (after T02): `_SIZE_FAILSAFE_VACUUM_PAGES` → pass as parameter or read from config
- `update_heartbeat`: `_MAX_CONSECUTIVE_HEARTBEAT_FAILURES` → config read
- `serve()`: consecutive heartbeat check uses this constant

Do NOT remove the `_HEARTBEAT_WRITE_TIMEOUT_SECONDS`, `_SHUTDOWN_DRAIN_TIMEOUT_SECONDS`, `_DRAIN_TIMEOUT_POOL_FRACTION`, or `_BUSY_TIMEOUT_MS` constants — these are not duplicated in DatabaseConfig.

Note: existing tests that `patch("hassette.core.database_service._RETENTION_INTERVAL_SECONDS", 0.1)` will need to be updated to patch the config field instead. This is a necessary test change (the patched constant no longer exists), not a behavior change.

### Step 2: Harden rollback error handling (FR#7)

In `_do_run_retention_cleanup`'s except block and `_insert_log_records`'s except block, wrap the `rollback()` call so a rollback failure doesn't mask the original exception:

```python
except Exception:
    try:
        await self.db.rollback()
    except Exception:
        self.logger.exception("Rollback failed after error in retention cleanup")
    self.logger.exception("Failed to run retention cleanup")
```

Same pattern for `_insert_log_records`, but note it re-raises after logging — preserve that:

```python
except Exception:
    try:
        await db.rollback()
    except Exception:
        self.logger.exception("Rollback failed after error in log record insert")
    raise
```

### Step 3: Add _insert_log_records error path test (FR#8)

Add a test to `tests/unit/core/test_database_service.py` (or the appropriate log_records test file):
- Mock `db.executemany` to raise `sqlite3.OperationalError`
- Assert `db.rollback()` was called
- Assert the exception re-raises to the caller (the write-queue worker)

### Step 4: Add run_size_failsafe and serve-loop tests (FR#9)

Add to `tests/integration/database/test_database_service.py`:
- Test `run_size_failsafe()` calls `_check_size_failsafe` via enqueue
- Test the guard clauses (`_db is None` returns early, `_db_write_queue is None` returns early)
- Test that `serve()` reaches the size-failsafe branch: patch `_SIZE_FAILSAFE_INTERVAL_SECONDS` (now the config field) to a small value alongside the existing heartbeat/retention patches in `test_serve_runs_heartbeat_and_retention`

### Verification

Run `prek -a` (lint + type check) and `pytest tests/unit/core/test_database_service.py tests/integration/database/test_database_service.py -v` and confirm all tests pass.

## Verify

- [ ] FR#6: All six hardcoded constants removed from module scope; `serve()`, `_check_size_failsafe`/`_run_failsafe_tier`, and `update_heartbeat` read from `self.hassette.config.database.*`
- [ ] FR#7: `rollback()` failures in `_do_run_retention_cleanup` and `_insert_log_records` do not mask the original exception
- [ ] FR#8: A test forces `executemany` to fail and asserts rollback + re-raise
- [ ] FR#9: `run_size_failsafe()` and its serve-loop branch have test coverage
- [ ] AC#4: All existing tests pass (some test patches may need updating from constant to config field — this is expected)
