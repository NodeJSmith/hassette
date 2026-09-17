---
task_id: "T02"
title: "Extract per-tier loop from size failsafe and add error handling"
status: "planned"
depends_on: ["T01"]
implements: ["FR#3", "FR#4", "AC#2", "AC#3"]
---

## Target Files

- modify: `src/hassette/core/database_service.py`
- modify: `tests/integration/database/test_database_service.py`
- modify: `tests/unit/core/test_database_service.py`

## Prompt

Read `design/specs/111-retention-decompose/tasks/context.md` and `design/specs/111-retention-decompose/design.md` (Approach section) first.

Read `src/hassette/core/database_service.py` — focus on `_check_size_failsafe` (the version after T01's refactoring — it now calls `_execute_failsafe_delete` but still has the full per-priority-tier loop inline).

### Step 1: Extract `_run_failsafe_tier`

Extract the per-priority inner loop (the `for iteration in range(...)` block) into a method on `DatabaseService`:

```python
async def _run_failsafe_tier(
    self,
    db: aiosqlite.Connection,
    group: list[RetentionTarget],
    batch_limit: int,
    max_iterations: int,
    max_size_mb: float,
) -> tuple[dict[str, int], bool]:
```

Returns `(deleted_by_table, under_limit)`:
- `deleted_by_table`: per-table deletion counts for this tier
- `under_limit`: True if `self.get_db_size_mb() <= max_size_mb` after the tier completes

The method contains the existing loop logic (order must match the original control flow in `database_service.py:874-908`):
1. For each iteration up to `max_iterations`:
   a. For each target in group: call `_execute_failsafe_delete(db, target, batch_limit)` — wrap in try/except per target (see Step 2)
   b. Commit — wrap in try/except (see Step 2b). On failure: log, break this tier's loop.
   c. If no rows deleted across the group: break (nothing left to delete) — this check MUST come after commit but BEFORE vacuum/checkpoint, matching the original short-circuit at line 890
   d. Vacuum + checkpoint — wrap in try/except (see Step 2b). On failure: log, break this tier's loop.
   e. Check size — if under limit: break
   f. If this was the last iteration: log the "capped at N iterations" warning
2. After the loop (regardless of exit reason — exhausted iterations, zero rows, or under limit): call `self.get_db_size_mb()` and set `under_limit` from the result. This matches the original code at line 910 which always recomputes size after the inner loop.
3. Return accumulated counts and `under_limit`

### Step 2: Add two-layer error handling (FR#4)

**Per-target** — wrap each `_execute_failsafe_delete` call in try/except:

```python
for target in group:
    try:
        n = await _execute_failsafe_delete(db, target, batch_limit)
        deleted_by_table[target.table] += n
        group_deleted += n
    except Exception:
        self.logger.exception(
            "Size failsafe: failed to delete from %s, continuing with remaining targets",
            target.table,
        )
```

This ensures a failure on one table (e.g., locked rows, corrupt index) does not prevent deletion of other tables in the same priority group.

**Per-iteration (two blocks)** — split to preserve the original control flow (commit → zero-delete check → vacuum/checkpoint):

```python
# Commit the batch
try:
    await db.commit()
except Exception:
    self.logger.exception(
        "Size failsafe: commit failed for %s, moving to next tier",
        group_label,
    )
    break

# Short-circuit if nothing was deleted (matches original line 890)
if group_deleted == 0:
    break

# Vacuum and checkpoint to reclaim space
try:
    vacuum_cursor = await db.execute(f"PRAGMA incremental_vacuum({_SIZE_FAILSAFE_VACUUM_PAGES})")
    await vacuum_cursor.close()
    await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
except Exception:
    self.logger.exception(
        "Size failsafe: vacuum/checkpoint failed for %s, moving to next tier",
        group_label,
    )
    break
```

This preserves the exact original control flow (vacuum/checkpoint are skipped on zero-delete iterations) while ensuring failures in either block don't abort the entire failsafe.

### Step 3: Refactor `_check_size_failsafe`

Replace the inner loop body with a call to `_run_failsafe_tier`. The outer method becomes orchestration-level:

```python
async def _check_size_failsafe(self) -> None:
    # ... early returns for disabled/under-limit ...
    # ... consecutive trigger warning ...

    db = self.db
    total_deleted_by_table: dict[str, int] = {t.table: 0 for t in _RETENTION_TABLES}

    priorities = sorted({t.priority for t in _RETENTION_TABLES})
    for priority in priorities:
        group = [t for t in _RETENTION_TABLES if t.priority == priority]
        tier_deleted, under_limit = await self._run_failsafe_tier(
            db, group, _SIZE_FAILSAFE_DELETE_BATCH, _SIZE_FAILSAFE_MAX_ITERATIONS,
            self.hassette.config.database.max_size_mb,
        )
        for table, count in tier_deleted.items():
            total_deleted_by_table[table] += count
        if under_limit:
            break

    # Summary logging — get current size for the log line since _run_failsafe_tier
    # does not return it (it returns under_limit as a bool)
    current_size = self.get_db_size_mb()
    deleted_summary = {table: count for table, count in total_deleted_by_table.items() if count > 0}
    if deleted_summary:
        parts = ", ".join(f"{count} {table}" for table, count in deleted_summary.items())
        self.logger.info("Size failsafe: deleted %s (%.1f MB remaining)", parts, current_size)
```

### Step 4: Add tests

Add to `tests/integration/database/test_database_service.py`:
- **Error resilience test (AC#3)**: Mock `_execute_failsafe_delete` to raise on one specific target but succeed on others. Verify that the successful targets still have rows deleted and the method does not raise.

Add to `tests/unit/core/test_database_service.py`:
- Test `_run_failsafe_tier` returns correct counts and `under_limit=True` when size drops below threshold
- Test `_run_failsafe_tier` returns `under_limit=False` when iterations are exhausted

### Verification

Run `pytest tests/unit/core/test_database_service.py tests/integration/database/test_database_service.py -v` and confirm all existing tests still pass plus the new tests.

## Verify

- [ ] FR#3: `_run_failsafe_tier` method exists on `DatabaseService`, accepts group/batch_limit/max_iterations/max_size_mb, returns (dict, bool)
- [ ] FR#4: A mocked DELETE failure on one target during failsafe does not prevent deletion of other targets — test passes
- [ ] AC#2: `_check_size_failsafe` delegates to `_run_failsafe_tier` for the per-priority inner loop
- [ ] AC#3: Error resilience test confirms per-target isolation
- [ ] AC#4: All existing tests pass unmodified — `pytest tests/unit/core/test_database_service.py tests/integration/database/test_database_service.py -v` shows zero failures
