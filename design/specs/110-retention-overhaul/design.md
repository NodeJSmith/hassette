# Design: Database Retention Overhaul

**Date:** 2026-09-16
**Status:** archived
**Scope-mode:** hold
**Research:** design/research/2026-09-16-telemetry-retention/research.md

## Problem

Framework-internal executions (`source_tier='framework'` — state_proxy, service_watcher, scheduler_service, runtime_query_service) account for 98.6% of execution-table rows on the live deployment (587K framework vs 8K app on a 497 MB database). A single `retention_days` window (default 7) treats all execution records equally, so the size failsafe runs constantly, evicting data indiscriminately to stay under the 500 MB limit. The result: app execution history goes back ~24 hours instead of the promised 7 days, and log records go back only minutes.

Two compounding defects make this worse:

1. **Wrong eviction order.** The size failsafe deletes `log_records` first (priority 0), then `executions` (priority 1), then `blocking_events` (priority 2). Logs are tiny (27 rows on the live DB) and the most valuable troubleshooting data — full stack traces for app errors. Deleting them first is the worst possible ordering.

2. **Shared transaction.** `_do_run_retention_cleanup()` wraps all DELETEs in one `BEGIN`/`COMMIT`. These are independent, table-scoped age-based deletes with no cross-table invariant. A failure in one silently rolls back all others for the entire hourly cycle, with only a generic log message that names no target.

## Goals

- Framework execution records are retained for 1 day (configurable via `framework_retention_days`); app execution records are retained for 7 days (existing `retention_days` default). The two windows are independent.
- Under size pressure, the failsafe deletes framework executions first, then blocking events, then app executions, then log records — preserving the most valuable data longest.
- Each retention target commits independently. A failure in one table's cleanup does not prevent others from completing.
- Clear per-tier deletion count log lines every hour, and a warning when the failsafe exhausts all tiers without bringing the DB under the limit.

## Non-Goals

- Per-app configurable retention (#651).
- Anomaly-only recording for framework executions (#2256) — changes what gets *written*, not what gets *deleted*.
- Lightweight statistics aggregation (#672).
- Size-failsafe visibility in the API/UI (#1753).
- Tier-aware retention for `log_records` — log retention uses `log_retention_days` (default 3), which is not tier-aware and is not changing. Framework-tier log records with app `app_key` values (e.g. CommandExecutor logging app handler errors) are a known attribution gap but do not affect this overhaul since log retention is not tier-filtered.
- Tier-aware retention for `blocking_events` — the table carries the same `source_tier` column as `executions` and is similarly framework-skewed (queried against the live deployment during ship-time challenge review: 34 framework / 12 app, ~74%), but at 46 total rows it is negligible next to `executions`' ~77.5K rows and is not a size-pressure contributor. Deferred rather than extended for consistency's sake; revisit if size pressure on this table recurs.

## User Scenarios

### Operator: Self-hosted solo developer

- **Goal:** Troubleshoot why an automation didn't fire yesterday
- **Context:** Checking the web UI execution history and log viewer after noticing a problem

#### Normal operation

1. **Opens the web UI execution history for an app**
   - Sees: App-tier executions going back 7 days; framework executions going back 1 day
   - Decides: Filters to the relevant app and time range
   - Then: Finds the execution record with error details and linked log entries

#### Database under size pressure

1. **Database approaches 500 MB between hourly cleanup cycles**
   - Sees: Nothing (automatic). Framework executions deleted first on next failsafe run
   - Then: If still over limit after framework cleanup, blocking events deleted next, then app executions, then log records. Log records — the stack traces — survive longest.

#### First run after upgrade

1. **Upgrades hassette to a version with `framework_retention_days` (default 1)**
   - Sees: The first several hourly retention passes clear up to 6 days of accumulated framework rows — `_RETENTION_MAX_BATCHES_PER_TARGET` caps each pass at 100,000 rows per target, so a 587K-row backlog takes roughly 6 hourly cycles to fully clear, not one
   - Then: Once caught up, subsequent hourly passes delete only ~1 hour's worth of new framework rows (steady state)

## Functional Requirements

- **FR#1** `DatabaseConfig` exposes a `framework_retention_days` field (integer, minimum 1, default 1) that controls the retention window for `source_tier='framework'` execution records independently of `retention_days`.
- **FR#2** Config validation rejects `framework_retention_days > retention_days` with an error message naming both fields and their current values.
- **FR#3** `_do_run_retention_cleanup()` deletes framework executions using `framework_retention_days` and app executions using `retention_days`, each filtered by `source_tier` via parameterized SQL.
- **FR#4** Each `_RETENTION_TABLES` target commits independently in `_do_run_retention_cleanup()`. A failure in one target is logged with the target's `failsafe_label` and does not prevent subsequent targets from running.
- **FR#5** Parent-guard deletes (retired listeners and scheduled_jobs) commit in their own transaction after all `_RETENTION_TABLES` targets. They continue to use `retention_days` as the cutoff.
- **FR#6** Size failsafe priority order is: framework executions (1), blocking events (2), app executions (3), log records (4). Framework data is deleted first; log records are deleted last.
- **FR#7** Deletion-count logging in both cleanup paths keys by `failsafe_label` so two executions entries produce distinct log lines. Per-target log lines in `_do_run_retention_cleanup()` include elapsed duration alongside count (e.g. "deleted 1,200 framework executions in 0.8s") to correlate long-running deletes with any subsequent heartbeat timeouts.
- **FR#8** `_do_run_retention_cleanup()` batches each target's DELETE in 1000-row chunks (matching the size failsafe's batch pattern) with a commit between each batch, bounding each batch's transaction and write-lock duration. Batching does **not** let other write-queue items interleave mid-pass — `db_write_worker()` dequeues and awaits the entire multi-target, multi-batch cleanup coroutine as a single queue item, so a heartbeat or live telemetry write queued during a cleanup pass still waits for the whole pass to finish, not just the current batch. The existing `_HEARTBEAT_WRITE_TIMEOUT_SECONDS` timeout on `update_heartbeat()` remains the actual safety net against a long-running pass; see #2265 for the queue-monopolization follow-up.
- **FR#9** Size failsafe logs a warning when all priority tiers are exhausted and the database remains over `max_size_mb`. Uses a consecutive counter (paralleling the existing `_consecutive_size_triggers` pattern) so the log message includes how many consecutive cycles the exhausted state has persisted.

## Edge Cases

- **First run after upgrade:** The first hourly retention pass has up to 6 days of accumulated framework rows to purge. The batched DELETE pattern (matching the failsafe's existing 1000-row batch + commit approach) bounds each individual batch's transaction and write-lock duration, and its per-batch commits give partial progress durability if the pass is interrupted. It does **not** let the write-queue worker yield to other queued writes mid-pass — see FR#8. Without batching, a single large DELETE could still hold the write lock for the same total duration in one transaction instead of many small ones; with batching, a long-running pass is a sequence of small commits rather than one large uncommitted transaction, which bounds lock duration per statement even though the overall pass length (and therefore how long other queue items wait behind it) is unchanged. The size failsafe only activates when the DB exceeds `max_size_mb` (which may not be the case for a large backlog that's merely slow to prune), so there is no independent fallback if the first-run pass itself causes problems — see #2265.
- **Config reload edge:** A user who previously set `framework_retention_days = 3` and later edits only `retention_days` down to `2` fails the cross-field validator. The error message names both fields and their current values so the user knows which to fix.
- **Per-target failure isolation:** If one target's DELETE fails (e.g., transient `OperationalError`), the remaining targets still run and commit independently. The failed target's data persists until the next hourly cycle. Parent-guard deletes still run — they query `executions` directly via `NOT EXISTS`.
- **Dict key collision:** Two `RetentionTarget` entries share `table="executions"`. All deletion-count dicts key by `failsafe_label` to avoid the framework count being silently overwritten by the app count.
- **All tiers exhausted:** If the failsafe deletes everything it can from all four priority tiers and the DB is still over `max_size_mb`, the remaining space is consumed by data the failsafe doesn't manage (sessions table, WAL files, SQLite internal overhead). A warning log fires — at most once per failsafe run (hourly).

## Acceptance Criteria

- **AC#1** With `framework_retention_days=1` and `retention_days=7`: framework executions at 2 days old are deleted; app executions at 2 days old are kept. Realistic time-distribution test: seed rows at 0.5, 1.5, 2, 5, 8 days old for both tiers and assert exact survival set. (FR#1, FR#3)
- **AC#2** `DatabaseConfig(framework_retention_days=5, retention_days=3)` raises `ValidationError` with a message containing both field names and values. (FR#2)
- **AC#3** Forcing one target's DELETE to raise does not prevent subsequent targets from completing their own commits. (FR#4)
- **AC#4** Size failsafe with mixed-tier seed (both framework and app `executions` rows interleaved by age, plus blocking_events and log_records), DB over limit: framework rows deleted first and the deleted rows are the oldest N of the framework tier specifically (not globally oldest N). If framework deletion resolves the overage, app rows and log records untouched. Full priority chain tested with a seed where the globally-oldest row is app-tier to catch the subquery-scoping bug. (FR#6)
- **AC#5** Retention cleanup log output distinguishes framework execution count from app execution count, and includes elapsed duration per target. (FR#7)
- **AC#6** Size failsafe with all tiers exhausted and DB still over limit: a warning log is emitted with consecutive-cycle count. (FR#9)
- **AC#7** `prek -a` passes.
- **AC#8** Docs config table includes `framework_retention_days`; `retention_days` description says "app-tier execution records"; "How Retention Works" accurately describes all four retention targets, per-target transactions, and the updated size failsafe priority order. Doc-persona-review and doc-accuracy-review pass on touched pages.
- **AC#9** Parent-guard deletes (listeners, scheduled_jobs) run after all `_RETENTION_TABLES` targets have committed, and use `retention_days` as the cutoff. Test: seed a retired listener with `retired_at` older than `retention_days` but with no recent executions, run retention cleanup, assert it is deleted only after the execution-tier targets have committed. (FR#5)
- **AC#10** Retention cleanup DELETE is batched in 1000-row chunks with a commit between each batch. Test: seed >1000 framework executions older than `framework_retention_days`, run retention cleanup, assert all are deleted across multiple batches (verify batch count > 1). (FR#8)

## Key Constraints

- `source_tier` column and index (`idx_exec_source_tier_time`) already exist on `executions` (migration 001). No schema migration needed.
- The `RetentionTarget` field for tier filtering must use the existing `SourceTier = Literal["app", "framework"]` type (`types/types.py:63`) with parameterized SQL binding — not raw SQL string interpolation.
- Parent-guard deletes (listeners, scheduled_jobs) reference `executions` via `NOT EXISTS` subquery. They must run after all execution-tier deletes have committed, and they continue to use `retention_days` (the longer window) as the cutoff.
- `_check_size_failsafe()` operates under autocommit (`isolation_level=None`, no `BEGIN`). The explicit `db.commit()` after each batch (line 888) is load-bearing: `PRAGMA wal_checkpoint(TRUNCATE)` cannot run while a write lock is held — the code's own inline comment documents this. The per-batch commit-then-vacuum pattern is correct and should be preserved, not removed.
- The test DDL in `_fixtures_telemetry.py` must be extended to include `source_tier` on the `executions` table before tier-aware tests can be written.

## Dependencies and Assumptions

- `SourceTier = Literal["app", "framework"]` in `types/types.py:63` is the canonical source for valid tier values.
- The DB-level `CHECK (source_tier IN ('app', 'framework'))` constraint on `executions` ensures the two-tier filter is exhaustive — no row escapes both deletes.
- Accepted risk: the first-run backlog delete may transiently restart `DatabaseService` on installations with very large accumulated framework row counts, if retention cleanup and the size failsafe co-fire on the same hourly tick and together starve the heartbeat write past its 3-strike timeout. A restart does **not** self-heal this: `serve()` resets `last_retention_run` unconditionally, so the next retention attempt is a full `_RETENTION_INTERVAL_SECONDS` away regardless of how much backlog remained, and `on_initialize()` does not re-kick retention on startup the way it does the size failsafe. On constrained hardware with a large backlog this can recur roughly hourly without converging. See #2265 for the underlying queue-monopolization root cause, and #2266 for the restart/reset gap specifically.
- `HassetteConfig` is fully reconstructed on config reload (`config.py:341-350`, `__init__(**self._init_kwargs)`). All config values are read live at point of use, not cached — no stale-cache risk after reload.

## Architecture

### Config

`DatabaseConfig` in `src/hassette/config/models.py` gains one field:

```python
framework_retention_days: int = Field(default=1, ge=1)
```

A `model_validator(mode="after")` on `DatabaseConfig` enforces `framework_retention_days <= retention_days`, with a `ValueError` naming both fields and their current values — following the `LifecycleConfig.validate_sync_executor_shutdown_budget` pattern (`models.py:371-379`).

### RetentionTarget

The `RetentionTarget` dataclass (`database_service.py:110-118`) gains a typed field:

```python
source_tier: SourceTier | None = None
```

When set, both `_do_run_retention_cleanup()` and `_check_size_failsafe()` add `AND source_tier = ?` to their DELETE queries with parameterized binding. When `None`, queries are unchanged.

### _RETENTION_TABLES

The list changes from 3 entries to 4, with reordered priorities:

| # | target | source_tier | retention_days_getter | priority | failsafe_label |
|---|--------|-------------|----------------------|----------|----------------|
| 0 | executions (framework) | `"framework"` | `cfg.database.framework_retention_days` | 1 | framework executions |
| 1 | blocking_events | `None` | `cfg.database.retention_days` | 2 | blocking events |
| 2 | executions (app) | `"app"` | `cfg.database.retention_days` | 3 | app executions |
| 3 | log_records | `None` | `cfg.logging.log_retention_days` | 4 | log records |

Size failsafe deletion order (lowest priority first): framework executions → blocking events → app executions → log records. This maximizes preservation of the two most valuable data types (app executions and logs).

### _do_run_retention_cleanup()

Restructured from one shared transaction to per-target commits with per-target error handling:

```python
for target in _RETENTION_TABLES:
    try:
        target_start = time.monotonic()
        cutoff = now - (target.retention_days_getter(config) * SECONDS_PER_DAY)
        where = f"{target.timestamp_col} < ?"
        params: list[Any] = [cutoff]
        if target.source_tier:
            where = f"source_tier = ? AND {where}"
            params.insert(0, target.source_tier)
        total_deleted = 0
        while True:
            await self.db.execute("BEGIN")
            cursor = await self.db.execute(
                f"DELETE FROM {target.table} WHERE id IN "
                f"(SELECT id FROM {target.table} WHERE {where} LIMIT ?)",
                [*params, _RETENTION_DELETE_BATCH],
            )
            batch_count = cursor.rowcount or 0
            await self.db.commit()
            total_deleted += batch_count
            if batch_count < _RETENTION_DELETE_BATCH:
                break
        elapsed = time.monotonic() - target_start
        deleted_by_label[target.failsafe_label] = total_deleted
        if total_deleted > 0:
            self.logger.info(
                "Retention cleanup: deleted %d %s in %.1fs",
                total_deleted, target.failsafe_label, elapsed,
            )
    except Exception:
        await self.db.rollback()
        self.logger.exception("Retention cleanup failed for %s", target.failsafe_label)
        deleted_by_label[target.failsafe_label] = total_deleted  # record partial progress
        failed_labels.add(target.failsafe_label)
```

The `except` branch records `total_deleted` (already-committed batches) alongside the failure — partial progress from earlier batches is real and durable, so the log must reflect it. The summary log line (after the loop) includes both successful and partially-failed targets, with `failed_labels` distinguishing "target failed after N rows" from "target completed with 0 rows."

Batching uses the same 1000-row batch size as the size failsafe (`_RETENTION_DELETE_BATCH = 1000`). Each batch commits independently so the write-queue worker yields between batches, allowing heartbeat writes to interleave. The inner SELECT uses the same `WHERE` clause as the outer delete would, scoped to the batch limit.

Parent-guard deletes (listeners, scheduled_jobs) follow in their own transaction, using `retention_days` as the cutoff, unchanged in logic. **They only run when all `_RETENTION_TABLES` targets succeeded** — if `failed_labels` is non-empty, the guard is skipped for this cycle. This preserves the old safety invariant: the guard can only ever execute against a state where all upstream deletes completed. Without this gate, a sustained multi-cycle failure of one target could leave stale execution rows that trigger a `CHECK` constraint violation via `ON DELETE SET NULL` when the guard deletes their parent listener/job.

### _check_size_failsafe()

Already operates under autocommit (each DELETE commits individually). Changes:
1. Tier filter goes INSIDE the nested subquery — the inner SELECT must scope to the targeted tier so it selects the oldest N rows of that tier, not the globally oldest N. Corrected shape:
   ```sql
   DELETE FROM {table} WHERE id IN (
       SELECT id FROM {table}
       WHERE source_tier = ?
       ORDER BY {timestamp_col} ASC
       LIMIT ?
   )
   ```
   When `target.source_tier` is `None`, the `WHERE source_tier = ?` clause and its parameter are omitted entirely. The tier filter must NOT go on the outer DELETE — that would select globally-oldest rows then discard non-matching ones, deleting fewer than the batch size of the targeted tier.
2. Key `total_deleted_by_table` by `failsafe_label` instead of `target.table`
3. New priority numbers (1, 2, 3, 4)
4. Post-loop warning when all tiers exhausted and DB still over limit (with consecutive counter)

### Test DDL

Add `source_tier TEXT NOT NULL DEFAULT 'app' CHECK (source_tier IN ('app', 'framework'))` to the `executions` table in `TELEMETRY_TEST_DDL` (`_fixtures_telemetry.py:72-83`), matching the production schema from `001.sql:97-98`.

## Implementation Preferences

- Use `SourceTier` type from `src/hassette/types/types.py` for the `RetentionTarget.source_tier` field.
- Parameterized SQL (`?` binding) for all tier filtering.
- Follow existing test patterns in `tests/unit/core/test_log_records_retention.py`.
- Docs changes go through `doc-persona-review` and `doc-accuracy-review` per `.claude/rules/doc-rules.md` before shipping.

## Replacement Targets

- The single `executions` entry in `_RETENTION_TABLES` (priority 1) is replaced by two tier-specific entries (priorities 1 and 3).
- `log_records` priority changes from 0 (deleted first) to 4 (deleted last). Its `failsafe_label` changes from `"log pre-pass"` to `"log records"` to reflect its new non-pre-pass role.
- `blocking_events` priority number stays at 2 but its position in the deletion sequence changes: previously last-of-three (after the single `executions` target), now second-of-four (between framework and app executions).
- The shared `BEGIN`/`COMMIT` transaction in `_do_run_retention_cleanup()` is replaced by per-target transactions.
- The `deleted_by_table` dict keyed by `target.table` is replaced by `deleted_by_label` keyed by `target.failsafe_label` in both cleanup paths.

## Convention Examples

### RetentionTarget declaration

**Source:** `src/hassette/core/database_service.py:121-143`

```python
_RETENTION_TABLES: list[RetentionTarget] = [
    RetentionTarget(
        table="log_records",
        timestamp_col="timestamp",
        priority=0,
        retention_days_getter=lambda cfg: cfg.logging.log_retention_days,
        failsafe_label="log pre-pass",
    ),
    # ...
]
```

### Cross-field model_validator on a config group

**Source:** `src/hassette/config/models.py:371-379`

```python
@model_validator(mode="after")
def validate_sync_executor_shutdown_budget(self) -> "LifecycleConfig":
    if self.sync_executor_shutdown_timeout_seconds >= self.total_shutdown_timeout_seconds:
        raise ValueError(
            f"sync_executor_shutdown_timeout_seconds "
            f"({self.sync_executor_shutdown_timeout_seconds}) must be less than "
            f"total_shutdown_timeout_seconds ({self.total_shutdown_timeout_seconds})"
        )
    return self
```

### Per-batch commit in size failsafe

**Source:** `src/hassette/core/database_service.py:884-899`

```python
# Commit the batch before vacuuming.
await db.commit()

if group_deleted == 0:
    break

vacuum_cursor = await db.execute(f"PRAGMA incremental_vacuum({_SIZE_FAILSAFE_VACUUM_PAGES})")
await vacuum_cursor.close()
await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
```

## Alternatives Considered

**Keep shared transaction in retention cleanup.** Simpler, guarantees all-or-nothing per hourly cycle. Rejected: independent age-based deletes on different tables have no cross-table invariant requiring atomicity. A single failure currently skips all cleanup for the cycle — partial cleanup is better than no cleanup.

**Generic `extra_where: str | None` on RetentionTarget.** Would allow arbitrary SQL filter predicates. Rejected: the design only needs two hardcoded tier values. Typed `source_tier: SourceTier | None` names the actual domain column, uses parameterized binding, and structurally forecloses the "per-app retention via extra_where" path that #651 should own.

**Unbatched retention DELETE.** The original design deferred batching in `_do_run_retention_cleanup()` as accepted risk, relying on the size failsafe as a backstop. Rejected after challenge review identified that the failsafe only activates when the DB exceeds `max_size_mb` — the design's own motivating example (497 MB / 500 MB) is under the threshold, leaving no backstop for the first-run backlog. Batching matches the failsafe's existing proven pattern at minimal additional complexity.

**Same priority for framework and app executions.** Would delete both tiers simultaneously under size pressure. Rejected: the whole point is that framework data is disposable while app data should be preserved. Separate priorities directly encode this value ordering.

## Test Strategy

### Required Test Types

Unit (retention cleanup behavior, config validation, size failsafe priority ordering) and integration (full `DatabaseService` lifecycle with retention).

### Existing Tests to Adapt

- `tests/unit/core/test_log_records_retention.py` — `TestRetentionCleanup` and `TestSizeFailsafePrePass` need tier-aware assertions and new priority order.
- `tests/unit/core/_fixtures_telemetry.py` — `TELEMETRY_TEST_DDL` needs `source_tier` on `executions`.
- `tests/integration/database/test_database_service.py` — `test_retention_cleanup` (line 203) and `test_size_failsafe_*` tests need new priority order and tier filtering.

### New Test Coverage

- **FR#1, FR#3**: Realistic time-distribution test — seed rows at 0.5, 1.5, 2, 5, 8 days old for both tiers, assert exact survival set (framework: only 0.5d kept; app: 0.5, 1.5, 2, 5d kept; 8d deleted from both).
- **FR#2**: Config validation — rejects `framework_retention_days > retention_days`, error message contains both field names and values.
- **FR#4**: Per-target failure isolation — inject a failure into one target's DELETE, assert subsequent targets still commit.
- **FR#6**: Size failsafe full priority chain — seed all four tables, mock size still over limit across multiple tiers, assert framework rows gone first, then blocking_events, then app, then logs. Also: framework alone resolves overage → everything else untouched.
- **FR#7**: Logging key collision avoidance — two executions targets produce distinct log entries.
- **FR#8**: Batching — seed >1000 rows, verify multi-batch deletion with commits between batches.
- **FR#9**: Exhaustion warning — all tiers drained, DB still over limit, warning emitted with consecutive-cycle count.
- **blocking_events coverage**: Seed blocking_events rows, run retention and failsafe, assert correct deletion behavior and priority ordering (currently zero coverage for this table).

### Tests to Remove

No tests to remove — existing tests are adapted.

## Smoke Test

After implementation, run the test suite:

```bash
uv run nox -s dev
```

For manual verification on the live deployment: restart hassette with `framework_retention_days = 1` (default). After one retention cycle (~1 hour), check:

```bash
hassette listener --app <app_key> --since 7d   # should show multi-day app history
hassette log --app <app_key> --since 1h          # should show log records (not evicted)
```

The contrast with the current state (app history ~24h, logs ~minutes) is the observable success signal.

## Documentation Updates

- `docs/pages/core-concepts/snippets/database-telemetry/db_config.toml` — add `framework_retention_days = 1` line
- `docs/pages/core-concepts/database-telemetry.md` — add `framework_retention_days` to config table; update `retention_days` description to say "app-tier execution records"; rewrite "How Retention Works" to accurately name all four retention targets (log_records, framework executions, app executions, blocking_events), per-target transactions, and the updated size failsafe priority order; mention blocking_events in size-based retention description
- Run `doc-persona-review` and `doc-accuracy-review` on `core-concepts/database-telemetry` before shipping

## Impact

### Changed Files

- **modify** `src/hassette/config/models.py` — add `framework_retention_days` field + `model_validator`
- **modify** `src/hassette/core/database_service.py` — add `source_tier` to `RetentionTarget`; restructure `_RETENTION_TABLES` (4 entries, new priorities); rewrite `_do_run_retention_cleanup()` for per-target transactions, tier filtering, and labeled logging; update `_check_size_failsafe()` for tier filtering, labeled logging, and exhaustion warning
- **modify** `tests/unit/core/_fixtures_telemetry.py` — add `source_tier` column to `TELEMETRY_TEST_DDL` executions table
- **modify** `tests/unit/core/test_database_service.py` — adapt RetentionTarget structure tests (count, priority ordering, getter tests) for 4 entries and `by_label` indexing
- **modify** `tests/unit/core/test_log_records_retention.py` — adapt existing tests, add tier-aware retention tests, per-target failure isolation test, priority ordering test, exhaustion warning test, blocking_events coverage
- **modify** `tests/integration/database/test_database_service.py` — adapt retention and failsafe tests for new priorities and tier filtering
- **modify** `docs/pages/core-concepts/snippets/database-telemetry/db_config.toml` — add new field
- **modify** `docs/pages/core-concepts/database-telemetry.md` — rewrite config table and retention sections

### Behavioral Invariants

- Parent-guard deletes (listeners, scheduled_jobs) continue to use `retention_days` as the cutoff. Their `NOT EXISTS` subquery against `executions` is unchanged in logic.
- `log_retention_days` (on `LoggingConfig`, default 3) is unchanged and independent.
- Size failsafe still commits per-batch and vacuums between iterations. Only priority order and tier filtering change.
- The web UI reads execution and log data through `TelemetryQueryService` — unaffected, it reads whatever data exists.
- The CLI (`hassette listener`, `hassette log`) queries the same data — unaffected.

### Blast Radius

- No external consumers. The retention/failsafe machinery is internal to `DatabaseService`.
- The `seed_db.py` script generates test data — it would benefit from a `source_tier` mix but is not blocking.
- Config schema gains one new field (`framework_retention_days`) with a sensible default. Existing configs are forward-compatible.

## Open Questions

None — all questions resolved during discovery, audit, and challenge review.

## Addendum

**2026-09-25 — FR#8 queue monopolization resolved by cap + timeout (#2265, #2282).** FR#8's
description of batching still holds: a retention pass remains a single write-queue item and does
not interleave with other writes. The resumable per-batch continuation was not built. What changed
is that the pass is now bounded and the writers stuck behind it no longer wait without limit:

- `DatabaseConfig.retention_max_batches_per_target` (default 100) caps how many batches one pass
  runs per target. Any remainder is left for the next cycle, so a pass occupies the queue for at
  most `targets × cap × retention_delete_batch` rows of deletes, however large the backlog.
- `DatabaseService.submit()` bounds how long a write may wait in the queue before it starts
  (`DatabaseConfig.write_submit_timeout_seconds`, default 60s). On expiry the write is withdrawn
  unexecuted and the caller gets `TimeoutError`. `persist_batch()` handles that as a retryable
  error (the same `RetryableBatch` path as `OperationalError`), so a long pass delays live
  telemetry and logs it rather than suspending the drain loop. Registration and session writes
  let the `TimeoutError` propagate like any other DB error.
- No separate in-flight guard was added. `serve()` still advances `last_retention_run` when a
  pass is enqueued, but with the batch cap a pass finishes far inside the 3600s interval, so a
  second pass cannot stack behind a still-running one in practice. Measured on desktop hardware
  against a 150k-row framework backlog: one capped pass deleted 100k rows in 0.46s, leaving 50k
  for the next cycle.
