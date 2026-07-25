---
task_id: "T03"
title: "Implement all 7 scenario generators and new factories"
status: "done"
depends_on: ["T02"]
implements: ["FR#3", "FR#10", "FR#11", "AC#5"]
---

## Summary

Implement the 6 remaining scenario generator functions (healthy, degraded, error, large-volume, lifecycle, adversarial) that were left as stubs in T02, plus the new test factories (`make_execution_record`, `make_blocking_event`, `make_log_record`) needed to build scenario data. Each scenario produces a complete, self-consistent dataset across all 6 telemetry tables using SeedContext methods exclusively.

## Target Files

- modify: `scripts/seed_db.py`
- modify: `src/hassette/test_utils/factories.py`
- read: `src/hassette/core/execution_record.py`
- read: `src/hassette/schemas/telemetry_models.py`
- read: `src/hassette/core/database_service.py`
- read: `src/hassette/web/telemetry_helpers.py`
- read: `src/hassette/migrations_sql/001.sql`
- read: `src/hassette/migrations_sql/005.sql`
- read: `design/specs/017-seed-db/design.md`

## Prompt

### New factories in `src/hassette/test_utils/factories.py`

Add three new keyword-only factory functions following the existing `make_listener_registration` / `make_job_registration` pattern (all keyword-only, sensible defaults, return the target type):

1. **`make_execution_record(**kw) -> ExecutionRecord`** — returns a frozen `ExecutionRecord` dataclass. Default `kind="handler"`, `status="success"`, `session_id=1`, `listener_id=1`, `job_id=None`. Generate a deterministic `execution_id` default (e.g. `"test_exec_0001"`). All timestamp defaults should be fixed values (not wall-clock).

2. **`make_blocking_event(**kw) -> dict[str, Any]`** — returns a dict matching the `blocking_events` table column shape (from `migrations_sql/005.sql` plus additions in `007.sql`). Default `tier="watchdog"`, `reason="attributed"`, `session_id=1`, `execution_id=None`. Read `src/hassette/schemas/telemetry_models.py` (`BlockingEvent` class) for the full field set.

3. **`make_log_record(**kw) -> dict[str, Any]`** — returns a dict matching the 13-column `_LOG_COLUMNS` shape from `database_service.py:53-67`. Defaults: `level="INFO"`, `logger_name="hassette.test"`, `message="test log"`, `execution_id=None`, `source_tier="app"`.

### Scenario generators in `scripts/seed_db.py`

Replace the `NotImplementedError` stubs from T02 with full implementations. Each scenario function takes a `SeedContext` and populates it. All data is hand-authored Python literals — no randomness.

Read `design/specs/017-seed-db/design.md` (Architecture § "Scenario definitions" table and § "Lifecycle field contract" table) for the exact specification of each scenario.

**Scenario specifications:**

1. **`scenario_healthy(ctx)`** — 5-6 fictional apps (e.g. `weather_watcher`, `garage_door`, `plant_monitor`, `media_controller`, `pet_feeder`). Each with 1 session (status `running`), 2-3 listeners, 1-2 jobs, 15-30 executions (90%+ success rate → excellent/good health). A few log records per app. No blocking events. All timestamps as offsets from the deterministic reference point.

2. **`scenario_degraded(ctx)`** — 5-6 apps with mixed health. 2-3 apps healthy (same as above). 2 apps with elevated error rates (30-50% errors → warning health). 1 app with a session showing boot issues (status `failure` on first session, then `running` on second). At least one DI failure execution. A few log records including error-level entries.

3. **`scenario_error(ctx)`** — 5-6 apps, all failing. High error rates (80%+ → critical health). Multiple crashed sessions (status `crashed`). Boot failures. Thread-leaked executions. Error and critical log records. Several blocking events.

4. **`scenario_large_volume(ctx)`** — 8-10 apps. 1000+ executions across all apps (target: enough to exercise frontend pagination). Many log records. Use deterministic loops with index-derived values for the volume: `for i in range(count): ctx.add_execution(make_execution_record(execution_id=f"large_{app_key}_{i:04d}", ...))`. Mix of success/error to get varied health.

5. **`scenario_lifecycle(ctx)`** — 4-5 apps demonstrating all lifecycle states. At least one retired listener (`retired_at` set, `cancelled_at` NULL). At least one cancelled job (`cancelled_at` set, `retired_at` NULL). At least one retired+cancelled listener (both set). Multiple sessions per app (crashed, restarted). Multi-instance apps (instance_index 0 and 1 for at least one app). See the Lifecycle Field Contract table in the design doc for reachable state combinations — lifecycle scenarios must only produce states reachable in production. Use raw `UPDATE ... SET retired_at = <timestamp>` after initial `ctx.add_listener()` to set retirement (SeedContext's `add_listener` mirrors `register_listener` which clears `retired_at`).

6. **`scenario_adversarial(ctx)`** — 3-4 apps designed to stress-test UI rendering. Long handler names (100+ characters). Long topic strings with nested predicates. 100+ listeners on one app. Unicode in app keys and listener names (e.g. Japanese, emoji). DI failure executions (`is_di_failure=True`). Thread-leaked executions (`thread_leaked=True`). Blocking events with both `watchdog` and `monkeypatch` tiers.

### Health threshold over-seeding (FR#11)

Read `src/hassette/web/telemetry_helpers.py` to find the current health computation thresholds. Seed error rates well past these boundaries. For example, if `warning` triggers at 20% errors, seed degraded apps at 40-50% errors. If `critical` triggers at 50%, seed error apps at 80%+. The exact rates don't matter — just ensure comfortable margin.

## Focus

- All timestamps must be deterministic: use `Instant.from_utc(2026, 1, 15, 12, 0)` as the base, with `TimeDelta` offsets. Never call `Instant.now()`.
- `execution_id` strings must be deterministic: use `f"{scenario}_{app_key}_{index:04d}"` pattern.
- `instance_name` strings: use `f"{class_name}.{instance_index}"` matching production default (see `src/hassette/core/app_registry.py`).
- For the `lifecycle` scenario, `retired_at`/`cancelled_at` must be set via raw SQL UPDATE after the initial INSERT (SeedContext's `add_listener`/`add_job` methods produce rows with NULL for both fields, matching production's `register_*` behavior). Add a method like `ctx.retire_listener(db_id, timestamp)` to SeedContext for this.
- The `empty` scenario (from T02) has zero rows — the other 6 must each produce rows in ALL 6 tables (sessions, listeners, jobs, executions, log_records, blocking_events) per FR#3.
- `blocking_events.execution_id` is nullable — watchdog-tier stalls can occur with no execution in progress.
- `log_records` can have `execution_id = NULL` (framework/startup logs outside execution context).

## Verify

- [ ] FR#3: each of the 6 non-empty scenarios produces rows in all 6 telemetry tables (verified by `SELECT COUNT(*) FROM <table>` for each)
- [ ] FR#10: all scenarios use fictional app keys not found in `examples/`
- [ ] FR#11: degraded scenario apps show warning health; error scenario apps show critical health (verified by running the health computation from `telemetry_helpers.py` against the seeded execution data)
- [ ] AC#5: all 7 scenarios generate without errors (`uv run python scripts/seed_db.py --scenario <name> --output /tmp/test-<name>.db` exits 0 for each)
