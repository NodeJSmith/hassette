# Design: Decompose retention/size-failsafe methods

**Date:** 2026-09-17
**Status:** draft
**Mode:** sketch

## Problem

`database_service.py` has two independent delete paths — age-based retention cleanup (`_do_run_retention_cleanup`, lines 757–829) and size-based failsafe (`_check_size_failsafe`, lines 840–918) — that share no infrastructure despite operating on the same `_RETENTION_TABLES` registry. The retention path has proper transaction semantics (BEGIN/commit/rollback); the failsafe path has none (no BEGIN, no error handling around DELETEs). Both paths inline their own DELETE SQL construction from `RetentionTarget` fields, and the failsafe path has no resilience against per-target or per-iteration failures.

## Goals

- Extract shared delete helpers to eliminate inline SQL duplication
- Fix the missing error handling in the size-failsafe DELETE path
- Reduce nesting in `_check_size_failsafe` by extracting the per-tier loop
- Wire the orphaned `DatabaseConfig` fields to replace hardcoded module constants
- Harden rollback error handling so `rollback()` failures don't mask the original exception
- Fill test coverage gaps for error paths (`_insert_log_records` rollback, `run_size_failsafe` entry point)
- Preserve all existing behavior (pin-behavior-first; no modifications to existing test assertions)

## Non-Goals

- Comb findings #2 and #3 from issue #2279 (parent-guard failure accumulation, end-of-cycle dual-cause reporting) — those variables (`failed_labels`, `capped_tier_label`, `any_tier_incomplete`) only exist on branch 2255, not main
- Removing `_RetentionBatchError` (#2268) — that class only exists on branch 2255
- Reducing `_check_size_failsafe` from 217 to 80 lines — the method is ~78 lines on main (the 217-line figure is from branch 2255's inflated version)
- Changing the parent-guard deletes (listeners/scheduled_jobs NOT EXISTS queries) — these are retention-path-specific and not part of the shared infrastructure

## Functional Requirements

- **FR#1** `_execute_target_delete(db, target, *, cutoff)` is a module-level function that constructs and executes a single age-based `DELETE FROM {table} WHERE {timestamp_col} < ?` query for one `RetentionTarget`, returning the number of rows deleted.
- **FR#2** `_execute_failsafe_delete(db, target, batch_limit)` is a module-level function that constructs and executes a single oldest-first batch `DELETE FROM {table} WHERE id IN (SELECT id ... ORDER BY {timestamp_col} ASC LIMIT ?)` query for one `RetentionTarget`, returning the number of rows deleted.
- **FR#3** `_run_failsafe_tier(self, db, group, batch_limit, max_iterations, max_size_mb)` is an extracted method containing the per-priority-tier inner loop from `_check_size_failsafe`. It iterates delete-vacuum-check cycles for one priority group and returns `(dict[str, int], bool)` — per-table deleted counts and whether the database is now under the size limit. When the first iteration deletes zero rows (nothing left to delete), `under_limit` is determined by a size check before returning — matching the original code which always recomputes size after the inner loop regardless of exit reason.
- **FR#4** The size-failsafe path handles per-iteration errors gracefully: a failure on any operation within an iteration (DELETE, commit, vacuum, checkpoint) logs the error, breaks the current tier's iteration loop, and continues to the next priority tier — rather than aborting the entire failsafe process. Per-target DELETE errors within an iteration log and continue with remaining targets in the group.
- **FR#5** `_do_run_retention_cleanup` calls `_execute_target_delete()` for each `RetentionTarget` instead of inlining the DELETE SQL, while preserving its existing BEGIN/commit/rollback transaction wrapping around the full set of deletes.
- **FR#6** The six hardcoded module-level constants (`_HEARTBEAT_INTERVAL_SECONDS`, `_RETENTION_INTERVAL_SECONDS`, `_SIZE_FAILSAFE_INTERVAL_SECONDS`, `_SIZE_FAILSAFE_MAX_ITERATIONS`, `_SIZE_FAILSAFE_DELETE_BATCH`, `_SIZE_FAILSAFE_VACUUM_PAGES`, `_MAX_CONSECUTIVE_HEARTBEAT_FAILURES`) are replaced with reads from the corresponding `DatabaseConfig` fields. The module constants are removed.
- **FR#7** `rollback()` calls in `_do_run_retention_cleanup` and `_insert_log_records` are wrapped in their own try/except so a rollback failure does not mask the original exception — the original exception is always logged.
- **FR#8** `_insert_log_records`'s rollback/re-raise path is covered by a test that forces `executemany` to fail and asserts the transaction is rolled back.
- **FR#9** `run_size_failsafe()` and its `serve()` integration are covered by tests — including the guard clauses and the serve-loop branch that calls it.

## Acceptance Criteria

- **AC#1** Both `_do_run_retention_cleanup` and `_check_size_failsafe` use the shared delete functions (`_execute_target_delete` / `_execute_failsafe_delete`) instead of inlining SQL (FR#1, FR#2, FR#5)
- **AC#2** `_check_size_failsafe` delegates to `_run_failsafe_tier` for the per-priority inner loop, reducing the method to orchestration-level logic only (FR#3)
- **AC#3** A simulated DELETE failure on one target during size-failsafe does not prevent deletion of other targets in the same tier (FR#4)
- **AC#4** All pre-existing test assertions continue to pass unmodified — `pytest tests/unit/core/test_database_service.py tests/integration/database/test_database_service.py -v` shows zero failures. New tests and necessary patch-target updates (module constant → config field) are additive, not behavioral changes.
- **AC#5** `_execute_target_delete` and `_execute_failsafe_delete` construct correct SQL from `RetentionTarget` fields (`target.table`, `target.timestamp_col`)
- **AC#6** The six hardcoded module-level constants are removed; `serve()`, `_check_size_failsafe`, and `update_heartbeat` read from `self.hassette.config.database.*` instead (FR#6)
- **AC#7** A forced `rollback()` failure in `_do_run_retention_cleanup` does not prevent the original exception from being logged (FR#7)
- **AC#8** A test forces `executemany` to fail in `_insert_log_records` and asserts rollback occurs and the exception re-raises (FR#8)
- **AC#9** `run_size_failsafe()` has a test exercising the enqueue wrapper and its guard clauses; `serve()` reaches the size-failsafe branch when `_SIZE_FAILSAFE_INTERVAL_SECONDS` is patched down (FR#9)

## Approach

### Transaction pattern difference is intentional

The two paths have fundamentally different transaction needs and must NOT share transaction management:

- **Retention cleanup** wraps all DELETEs in a single BEGIN/commit/rollback (lines 771, 812, 828). If any delete fails, the entire cycle rolls back. This is correct — retention is an all-or-nothing periodic sweep.
- **Size failsafe** commits after each batch (line 888) so `PRAGMA incremental_vacuum` and `PRAGMA wal_checkpoint(TRUNCATE)` can reclaim space between batches. These PRAGMAs require no active write lock. Wrapping the entire failsafe in a BEGIN would break the vacuum/checkpoint cycle.

The shared delete functions (`_execute_target_delete`, `_execute_failsafe_delete`) therefore execute a single DELETE and return the rowcount. They do NOT call BEGIN, commit, or rollback — the caller owns those.

### What the helpers share

1. SQL construction from `RetentionTarget` fields (`target.table`, `target.timestamp_col`)
2. Cursor handling and rowcount extraction

### Extraction targets

All new functions stay in `database_service.py` as module-level functions (the delete helpers) or methods on `DatabaseService` (the tier runner). Zero new files, zero external API changes.

- `_execute_target_delete(db, target, *, cutoff) -> int` — age-based delete
- `_execute_failsafe_delete(db, target, batch_limit) -> int` — oldest-first batch delete
- `_run_failsafe_tier(self, db, group, ...) -> tuple[dict[str, int], bool]` — per-tier loop extraction

### Error handling addition

`_run_failsafe_tier` has two error-handling layers:
- **Per-target**: each `_execute_failsafe_delete` call is wrapped in try/except. On failure: log the exception, record zero deletes for that target, continue with the next target in the group.
- **Per-iteration**: the commit + vacuum + checkpoint sequence is wrapped in try/except. On failure: log the exception, break the iteration loop for this tier, and return — the caller continues with the next priority tier. This prevents a vacuum or checkpoint failure under disk pressure from aborting the entire failsafe process.

## Changed Files

- modify: `src/hassette/core/database_service.py` — extract `_execute_target_delete`, `_execute_failsafe_delete`, `_run_failsafe_tier`; refactor `_do_run_retention_cleanup` and `_check_size_failsafe` to use them; add per-batch error handling in failsafe path; wire config fields replacing hardcoded constants; harden rollback error handling
- modify: `tests/integration/database/test_database_service.py` — add tests for AC#3 (error resilience), AC#9 (run_size_failsafe + serve-loop branch); update patches from module constants to config fields
- modify: `tests/unit/core/test_database_service.py` — add unit tests for extracted helpers, AC#8 (_insert_log_records error path); update patches from module constants to config fields
