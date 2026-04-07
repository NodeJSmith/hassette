---
proposal: "Investigate and fix test_size_failsafe_deletes_oldest_records and test_size_failsafe_loop_capped_at_10_iterations failures"
date: 2026-04-06
status: Draft
flexibility: Decided
motivation: "Two integration tests fail with 'database table is locked' on the #466 worktree but pass on main"
constraints: "Fix must not change checkpoint semantics; must work with database views introduced in migration 006"
non-goals: "Upgrading aiosqlite, removing views, changing the size failsafe algorithm"
depth: quick
---

# Research Brief: Size Failsafe WAL Checkpoint Lock Failure

**Initiated by**: Investigation of pre-existing test failures in worktree #466

## Context

### What prompted this

Two tests in `tests/integration/test_database_service.py` fail with `sqlite3.OperationalError: database table is locked`:
- `test_size_failsafe_deletes_oldest_records`
- `test_size_failsafe_loop_capped_at_10_iterations`

These tests pass on `main` but fail on the #466 branch, even with all branch changes stashed. The branch introduces migration 006 which adds database views.

### Current state

`DatabaseService._check_size_failsafe()` (line 364-431 in `src/hassette/core/database_service.py`) performs this sequence per iteration:

1. DELETE oldest records from `handler_invocations` and `job_executions`
2. `COMMIT`
3. `PRAGMA incremental_vacuum(100)` -- line 410
4. `PRAGMA wal_checkpoint(TRUNCATE)` -- line 411

Step 4 fails because step 3 leaves an un-finalized cursor via aiosqlite.

### Root cause (confirmed)

**aiosqlite cursor leak + database views = phantom reader lock.**

When `db.execute("PRAGMA incremental_vacuum(100)")` is called through aiosqlite, the returned `Cursor` object wraps a `sqlite3.Cursor` on the worker thread. aiosqlite does **not** automatically finalize (close) the underlying statement after `execute()` -- it relies on the caller to consume the result or close the cursor.

For most operations this is harmless. However, SQLite's `wal_checkpoint` requires that **no active statements** exist on the connection. An open cursor from `incremental_vacuum` counts as an active statement.

**Why this only manifests with views**: SQLite internally opens read cursors on tables referenced by views during statement preparation. The combination of an un-finalized `incremental_vacuum` statement and view-referencing read cursors creates a lock state that `wal_checkpoint` cannot acquire exclusive access through. Without views (migration 005 and earlier), the un-finalized cursor alone does not block the checkpoint.

### Evidence

| Scenario | Result |
|----------|--------|
| Migration 005 (no views) + vacuum + checkpoint | Passes |
| Migration 006 (with views) + vacuum + checkpoint | **Fails**: `database table is locked` |
| Migration 006 + vacuum + `cursor.close()` + checkpoint | Passes |
| Same operations via synchronous `sqlite3` (not aiosqlite) | Passes |
| All four checkpoint modes (PASSIVE/FULL/RESTART/TRUNCATE) | All fail with views |

Minimal reproduction:
```python
cursor = await db.execute("PRAGMA incremental_vacuum(100)")
# cursor left open -- un-finalized statement
await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # FAILS
```

Fix:
```python
cursor = await db.execute("PRAGMA incremental_vacuum(100)")
await cursor.close()  # finalize the statement
await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # SUCCEEDS
```

### Key constraints

- aiosqlite 0.22.1 (current)
- SQLite 3.50.4
- The views (`active_listeners`, `active_scheduled_jobs`) are required by the #466 feature

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Size failsafe method | 1 file (`database_service.py`, line 410) | Low | None -- purely additive |

### Suggested fix

In `_check_size_failsafe()`, close the cursor returned by `incremental_vacuum` before calling `wal_checkpoint`:

```python
# Line 410-411 in database_service.py — current code:
await db.execute(f"PRAGMA incremental_vacuum({_SIZE_FAILSAFE_VACUUM_PAGES})")
await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

# Fixed:
vacuum_cursor = await db.execute(f"PRAGMA incremental_vacuum({_SIZE_FAILSAFE_VACUUM_PAGES})")
await vacuum_cursor.close()
await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
```

### Defensive hardening (optional)

The same pattern could theoretically affect any PRAGMA sequence in the codebase. A defensive approach would close cursors after all PRAGMA calls in `_set_pragmas()` and `_check_size_failsafe()`. However, only the `incremental_vacuum` + `wal_checkpoint` sequence is confirmed to fail -- other PRAGMAs in `_set_pragmas()` work fine because they don't precede a checkpoint.

## Concerns

### This is not related to #466 changes

The fix belongs in the production code (`database_service.py`), not in the tests. The tests are correct -- they exercise `_check_size_failsafe()` which has a latent bug that was only exposed when migration 006 introduced views. The bug existed before but was dormant.

### aiosqlite upstream

This is arguably an aiosqlite design issue (cursors should auto-finalize PRAGMA results), but the library is unlikely to change this behavior. The explicit `close()` is the correct workaround.

## Recommendation

Apply the one-line fix (close the vacuum cursor). This is a confirmed root cause with a verified fix. No design doc or further research needed.

### Suggested next steps

1. Add `await vacuum_cursor.close()` after line 410 in `database_service.py`
2. Re-run the failing tests to confirm they pass
3. Consider adding a code comment explaining why the close is necessary (aiosqlite cursor leak + views interaction)
