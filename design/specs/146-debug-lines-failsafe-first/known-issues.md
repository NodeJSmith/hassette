# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: Partial-index use depends on SQLite matching a bound `level = ?`

Status: open
Recorded: 2026-11-05 (3675)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/retention_targets.py
- src/hassette/migrations_sql/022.sql

Issue:
`row_filter_terms` binds the level as a parameter. SQLite uses `idx_lr_debug_time` only if it proves the bound `level = ?` implies the index's `level = 'DEBUG'` predicate. A build that doesn't would make the DEBUG tier's failsafe delete, stale-row probe and age delete scan `idx_lr_time` instead: slow, not wrong.

Why deferred:
The match holds on SQLite 3.45.1 and 3.53.1 for every DEBUG-tier query path, and no failing build is known. D2 chose the bound parameter knowing this.

Recommended follow-up:
If a report shows slow DEBUG-tier deletes on some SQLite build, emit `level = 'DEBUG'` as a literal in `row_filter_terms` (safe: `RetentionTarget.level` is `Literal["DEBUG"]`).

Acceptance criteria:
- `EXPLAIN QUERY PLAN` for the DEBUG-tier queries shows `idx_lr_debug_time` on the affected build.

## KI-002: No test pins the age pass's use of the partial index

Status: open
Recorded: 2026-11-05 (3675)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- tests/integration/database/test_size_failsafe_exemption.py
- src/hassette/core/database_retention.py

Issue:
`test_debug_tier_queries_use_the_partial_index` explains the failsafe's own statements. The age delete and its stale-row probe also use `idx_lr_debug_time` today, but no test checks it, so a planner change or an edit to `_execute_target_delete` could move them off the index unnoticed.

Why deferred:
Both use the index on every build checked, and a regression costs speed only.

Recommended follow-up:
If the age pass's query shape changes, extend the test to capture and explain the age delete and its probe too.

Acceptance criteria:
- A test fails when the age pass's DEBUG delete stops using `idx_lr_debug_time`.

## KI-003: A capped or failed DEBUG age delete can be reported under both log labels

Status: open
Recorded: 2026-11-05 (3675)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/retention_targets.py

Issue:
DEBUG rows match both the `debug log records` and the level-agnostic `log records` target (D1). When the DEBUG age delete hits its batch cap or fails, `log records` sees the same rows, so the retention summary can name both labels as incomplete or failed.

Why deferred:
Only log output is affected, the trigger (more expiring DEBUG rows per hour than the batch cap, or a storage error) is rare, and D1 ratified the overlap.

Recommended follow-up:
If the doubled reporting confuses someone, partition the log targets so each row has one owner (D1 option B).

Acceptance criteria:
- A capped DEBUG age delete is reported once, under `debug log records`.

## KI-004: Migration 022's index build runs inside the startup migration timeout

Status: open
Recorded: 2026-11-05 (3675)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/migrations_sql/022.sql

Issue:
Upgrading builds `idx_lr_debug_time` in one scan of `log_records`, inside `database.migration_timeout_seconds` (120 s by default). A very large table on very slow storage could exceed it.

Why deferred:
A 2M-row table built in 0.38 s, a timed-out build rolls back cleanly, and raising `migration_timeout_seconds` recovers. Migration 016 set the same precedent.

Recommended follow-up:
If an upgrade report shows 022 timing out, build the index outside the migration timeout.

Acceptance criteria:
- Upgrading a database at the reported size completes migration 022 within the timeout.
