---
task_id: "T01"
title: "Extract shared delete functions and refactor both paths to use them"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#5", "AC#1", "AC#5"]
---

## Target Files

- modify: `src/hassette/core/database_service.py`
- modify: `tests/unit/core/test_database_service.py`
- modify: `tests/integration/database/test_database_service.py`

## Prompt

Read `design/specs/111-retention-decompose/tasks/context.md` and `design/specs/111-retention-decompose/design.md` (Approach section) first.

Read `src/hassette/core/database_service.py` — focus on:
- `RetentionTarget` dataclass (line ~111) and `_RETENTION_TABLES` (line ~121)
- `_do_run_retention_cleanup` (line ~757) — the age-based retention path
- `_check_size_failsafe` (line ~840) — the size-based failsafe path

### Step 1: Extract `_execute_target_delete`

Add a module-level async function above `DatabaseService`:

```python
async def _execute_target_delete(
    db: aiosqlite.Connection,
    target: RetentionTarget,
    *,
    cutoff: float,
) -> int:
```

This constructs and executes: `DELETE FROM {target.table} WHERE {target.timestamp_col} < ?`

Return `cursor.rowcount or 0`.

### Step 2: Extract `_execute_failsafe_delete`

Add a module-level async function:

```python
async def _execute_failsafe_delete(
    db: aiosqlite.Connection,
    target: RetentionTarget,
    batch_limit: int,
) -> int:
```

This constructs and executes the oldest-first batch delete:
`DELETE FROM {target.table} WHERE id IN (SELECT id FROM {target.table} ORDER BY {target.timestamp_col} ASC LIMIT ?)`

Return `cursor.rowcount or 0`.

### Step 3: Refactor `_do_run_retention_cleanup`

Replace the inline DELETE SQL at line ~775-779 with a call to `_execute_target_delete(self.db, target, cutoff=cutoff)`. Keep the BEGIN/commit/rollback wrapping exactly as-is — the function does not manage transactions. Keep the parent-guard deletes (listeners/scheduled_jobs NOT EXISTS queries) inline — they are retention-path-specific.

### Step 4: Refactor `_check_size_failsafe`

Replace the inline DELETE SQL at line ~877-883 with a call to `_execute_failsafe_delete(db, target, _SIZE_FAILSAFE_DELETE_BATCH)`. Keep the commit and vacuum/checkpoint calls exactly where they are.

### Step 5: Add a rollback pin test

Add one integration test to `tests/integration/database/test_database_service.py` that pins `_do_run_retention_cleanup`'s rollback-on-partial-failure behavior BEFORE the refactor touches it:
- Mock `self.db.execute` to raise on the *second* `RetentionTarget` in `_RETENTION_TABLES`
- Assert (a) `_do_run_retention_cleanup` does not propagate the exception, and (b) the row deleted for the *first* target is still present — i.e., `rollback()` actually reverted it
This is the characterization test that makes "refactor" a checkable claim per `refactoring-discipline.md`.

### Step 6: Add unit tests

Add tests to `tests/unit/core/test_database_service.py` for the two extracted functions:
- Test `_execute_target_delete` deletes rows older than cutoff and returns the count
- Test `_execute_failsafe_delete` deletes the oldest N rows and returns the count

Use an in-memory SQLite database for these tests — they test SQL construction, not DatabaseService wiring.

### Verification

Run `pytest tests/unit/core/test_database_service.py tests/integration/database/test_database_service.py -v` and confirm all existing tests still pass plus the new tests.

## Verify

- [ ] FR#1: `_execute_target_delete` exists as a module-level function, constructs age-based DELETE SQL, returns rowcount
- [ ] FR#2: `_execute_failsafe_delete` exists as a module-level function, constructs oldest-first batch DELETE SQL, returns rowcount
- [ ] FR#5: `_do_run_retention_cleanup` calls `_execute_target_delete` instead of inlining the DELETE SQL
- [ ] AC#1: Both `_do_run_retention_cleanup` and `_check_size_failsafe` use the shared delete functions
- [ ] AC#5: Both functions construct correct SQL from `RetentionTarget` fields
- [ ] AC#4: All existing tests pass unmodified — `pytest tests/unit/core/test_database_service.py tests/integration/database/test_database_service.py -v` shows zero failures
- [ ] Rollback pin test passes: a mid-loop failure in `_do_run_retention_cleanup` triggers rollback and reverts prior deletes
