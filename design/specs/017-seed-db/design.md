# Design: Deterministic DB Seeding Script

**Date:** 2026-07-25
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-07-25-deterministic-db-seeding/research.md

## Problem

There is no way to see the hassette monitoring dashboard in edge-case states (empty install, degraded health, high error rates, large data volumes) without manually orchestrating a real Home Assistant instance and waiting 60-90 seconds for demo apps to organically produce telemetry. The existing demo apps (`demo_stimulator`, `backpressure_demo`) are slow, non-deterministic, and can't reliably produce specific failure states on demand. This blocks frontend QA, CLI doc generation, visual regression screenshots, and demos.

## Goals

- All 7 named scenarios generate valid, referentially consistent SQLite databases on demand
- `hassette` CLI commands (`status`, `app`, `listener`, `job`, `log`) return meaningful output against every seeded DB
- Running the script twice for the same scenario produces identical database state
- Schema drift between the seeder and the real write path is caught at generation time, not at render time

## Non-Goals

- Checked-in DB files (revisit if a consumer needs instant access without running the script)
- CI freshness checks for seed DBs
- HA-optional startup mode (separate issue #1435)
- MSW browser scenarios (#760 Phase 1-2 — independent, covers transport-level concerns only)
- Changes to the demo stack
- CLI `hassette seed` subcommand (this is a dev script in `scripts/`, not shipped CLI surface)
- Screenshot pipeline integration (blocked on #1435)
- Dashboard grid/apps list rendering of seeded data (blocked on #1436 — manifest-driven views can't show fictional app keys)

## User Scenarios

### Developer: QA engineer or solo maintainer

- **Goal:** See the dashboard in a specific state to verify UI behavior
- **Context:** During frontend development or before a UI-related PR

#### Seed and query a degraded database

1. **Run the seed script**
   - Runs: `uv run python scripts/seed_db.py --scenario degraded --output /tmp/hassette-degraded.db`
   - Sees: script completes with a summary of what was generated (app count, execution count, health statuses)
   - Then: a SQLite file exists at the output path

2. **Query the seeded database via CLI**
   - Runs: `hassette --url http://localhost:8126 status` (with hassette pointed at the seeded DB)
   - Sees: realistic status output showing mixed health states
   - Then: can iterate on UI components knowing the data shape is deterministic

#### Generate all scenarios for comparison

1. **Run the script for each scenario**
   - Runs: `uv run python scripts/seed_db.py --scenario healthy --output /tmp/seed-healthy.db` (repeated for each scenario)
   - Sees: each scenario produces a distinct, deterministic database
   - Then: can swap databases to compare UI behavior across states

## Functional Requirements

- **FR#1** The script accepts `--scenario <name>` to select which dataset to generate, from a fixed set of 7 named scenarios
- **FR#2** The script accepts `--output <path>` to specify where to write the SQLite database (defaults to a path in the current directory)
- **FR#3** Each scenario produces a complete dataset across all 6 telemetry tables: `sessions`, `listeners`, `scheduled_jobs`, `executions`, `log_records`, `blocking_events`
- **FR#4** All data within a scenario is referentially consistent: every `executions.listener_id`/`job_id`/`session_id` points to a real row; every `log_records`/`blocking_events` `execution_id` matches a real `executions.execution_id`
- **FR#5** Running the script twice for the same scenario produces identical database content — same rows in the same order across all tables (deterministic timestamps, deterministic IDs, no wall-clock dependencies). SQLite internal page layout may vary; logical equality (row-by-row query comparison) is the verification standard.
- **FR#6** The script sets `PRAGMA foreign_keys = ON` on its connection and runs `PRAGMA foreign_key_check` after all inserts complete; FK violations abort the run
- **FR#7** A post-seed consistency assertion checks that all non-null `execution_id` values in `log_records` and `blocking_events` match an existing `executions.execution_id`; mismatches abort the run
- **FR#8** Each scenario's insert sequence is wrapped in a single transaction (`BEGIN IMMEDIATE`/`COMMIT`) with rollback on error; the output file is written to a temp path and atomically swapped via `os.replace()` only after integrity checks pass
- **FR#9** Each run produces a fresh database — the atomic swap (`os.replace()` from FR#8) handles replacing any existing file at the output path; no in-place upsert or append
- **FR#10** The script uses fictional app keys (not tied to `examples/` directory apps)
- **FR#11** Health-determining error rates in degraded/error scenarios are over-seeded well past threshold boundaries so minor threshold adjustments don't change the displayed health status

## Edge Cases

- **Empty scenario**: the `empty` scenario generates a database with the schema applied but zero rows in any table — the script must handle the "nothing to insert" case without errors
- **Large-volume pagination**: the `large-volume` scenario must produce enough rows in `executions` and `log_records` that frontend pagination is exercised (target: 1000+ executions across all apps)
- **Adversarial string lengths**: the `adversarial` scenario includes handler names, topics, and predicates that exceed typical UI column widths (100+ characters) and include Unicode
- **Cancelled + retired combinations**: the `lifecycle` scenario must only produce `retired_at`/`cancelled_at` combinations that are reachable in production (see Architecture — Lifecycle Field Contract)
- **Nullable execution_id**: `log_records` and `blocking_events` can have `execution_id = NULL` (framework logs, watchdog stalls with no execution context) — the consistency assertion must not flag nulls as dangling references

## Acceptance Criteria

- **AC#1** `uv run python scripts/seed_db.py --scenario healthy --output /tmp/test.db` exits 0 and produces a non-empty SQLite file (FR#1, FR#2)
- **AC#2** Running the script twice with the same `--scenario` and `--output` produces files with identical `SELECT * FROM <table> ORDER BY id` output for all 6 tables (FR#5)
- **AC#3** Intentionally inserting a dangling `listener_id` in a scenario definition causes the script to abort with an FK violation error (FR#6)
- **AC#4** Intentionally inserting a dangling `execution_id` in `log_records` causes the script to abort with a consistency assertion error (FR#7)
- **AC#5** All 7 scenarios (`healthy`, `empty`, `degraded`, `error`, `large-volume`, `lifecycle`, `adversarial`) generate without errors (FR#1, FR#3)
- **AC#6** `hassette status`, `hassette app`, `hassette listener --app <key>`, `hassette job`, and `hassette log --app <key>` return meaningful output (exit 0, non-empty tables) when pointed at each non-empty seeded DB (FR#3, FR#4)
- **AC#7** `prek -a` passes with the seed script and any modified source files (lint + type check)

## Key Constraints

- Do not use `INSERT OR REPLACE` or `ON CONFLICT DO NOTHING` in the seed script — these silently corrupt auto-increment IDs or skip rows. The script always writes a fresh file; conflict handling is unnecessary.
- Do not introduce Faker, Mimesis, or any RNG-based generation library. All scenario data is hand-authored and fully deterministic. The `large-volume` scenario uses deterministic loops with index-derived values, not seeded random generators.
- Do not reuse `TelemetryRepository` methods directly (they are async, require `aiosqlite`, and `insert_blocking_event` silently swallows errors). Import the param builder functions only.
- `scheduled_jobs.repeat` must be hardcoded to `0` in any extracted `job_insert_params` function — it is not a field on `ScheduledJobRegistration` and has no CHECK constraint protecting the invariant.

## Dependencies and Assumptions

- **hassette package installed**: the script imports from `hassette.core` (migration runner, param builders, dataclasses) and must run via `uv run python scripts/seed_db.py`
- **HA-optional startup (#1435)**: until resolved, seeded DBs cannot be used with the hassette web server without a running HA instance. CLI queries require a running hassette instance pointed at the seeded DB.
- **Dashboard manifest gap (#1436)**: the dashboard grid and apps list are driven by in-memory app manifests, not the telemetry DB. Fictional app keys in seed data are invisible on these views. Per-app detail pages (queried by `app_key` directly) work.
- **Schema stability**: the telemetry schema (migrations 001-010) is considered stable per design spec 068. New migrations would require updating the seed script's scenario data.

## Architecture

### Script structure

A single `scripts/seed_db.py` following the existing convention (`scripts/export_schemas.py`): module docstring with Usage section, `argparse.ArgumentParser` in a `def main()` function, `if __name__ == "__main__": main()` guard.

### Scenario registry

A plain dict literal mapping scenario names to generator callables:

```python
SCENARIOS: dict[str, Callable[[SeedContext], None]] = {
    "healthy": scenario_healthy,
    "empty": scenario_empty,
    "degraded": scenario_degraded,
    "error": scenario_error,
    "large-volume": scenario_large_volume,
    "lifecycle": scenario_lifecycle,
    "adversarial": scenario_adversarial,
}
```

No enum, no plugin discovery, no directory-per-scenario. Add complexity only when a concrete second consumer needs scenario introspection.

### SeedContext: intermediate ID-graph builder

A class that owns cross-table ID bookkeeping and insert ordering:

```python
@dataclass
class SeedContext:
    cursor: sqlite3.Cursor
    session_ids: list[int]  # populated by add_session()
    listener_ids: dict[tuple[str, int, str], int]  # (app_key, instance_index, name) -> db_id
    job_ids: dict[tuple[str, int, str], int]  # (app_key, instance_index, job_name) -> db_id
    execution_ids: list[str]  # execution_id strings for log/blocking correlation

    def add_session(self, ...) -> int: ...
    def add_listener(self, registration: ListenerRegistration) -> int: ...
    def add_job(self, registration: ScheduledJobRegistration) -> int: ...
    def add_execution(self, record: ExecutionRecord) -> str: ...
    def add_log_record(self, execution_id: str | None, ...) -> None: ...
    def add_blocking_event(self, session_id: int | None, ...) -> None: ...
```

Each `add_*` method calls the appropriate param builder, executes the INSERT via a sync `insert_row` helper, and tracks the returned ID. Scenario generators call `SeedContext` methods exclusively — they never write raw SQL.

### Write path: param builders + sync insert helper

The seed script imports the param builder functions from `hassette.core.telemetry.repository` (with underscore prefix removed) to build INSERT parameter dicts, then executes them via a thin sync helper:

```python
def insert_row(cursor: sqlite3.Cursor, sql: str, params: dict[str, Any]) -> int:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return row[0]  # RETURNING id
```

For tables without RETURNING (log_records, blocking_events — no integer PK returned), the helper returns `cursor.lastrowid`.

### Param builder extraction

Three param builder functions, all module-level in `repository.py`:
- `execution_insert_params(record: ExecutionRecord) -> dict[str, Any]` — exists as `_execution_insert_params`, drop prefix
- `listener_insert_params(registration: ListenerRegistration) -> dict[str, Any]` — exists as `_listener_insert_params`, drop prefix
- `job_insert_params(registration: ScheduledJobRegistration) -> dict[str, Any]` — extract from inline dict in `register_job()`, hardcode `repeat=0`

`_EXECUTION_INSERT_SQL` exists in `repository.py` but does NOT include `RETURNING id` — it is used only for `executemany` batch inserts. The seed script constructs its own INSERT SQL for all three record types:
- For listeners and jobs: plain `INSERT INTO ... (...) VALUES (...) RETURNING id` built from the param dict keys (need the autoincrement `id` for FK references in executions)
- For executions: plain `INSERT INTO ... (...) VALUES (...)` built from the param dict keys — no `RETURNING` needed since the `execution_id` string is already known from the `ExecutionRecord` and is what `log_records`/`blocking_events` reference

### Log records write path

`log_records` insert shape lives in `database_service.py` (`_LOG_COLUMNS` tuple with 13 columns, `_LOG_INSERT_SQL` constant, `_insert_log_records` method), not in `repository.py`. `_LOG_INSERT_SQL` is already a ready-to-use INSERT string built from `_LOG_COLUMNS` — the seed script can import it directly (after dropping the underscore prefix) rather than reconstructing the SQL. The 13 columns are: `seq, timestamp, level, logger_name, func_name, lineno, message, exc_info, app_key, instance_name, instance_index, execution_id, source_tier`.

### Integrity checks

1. `PRAGMA foreign_keys = ON` immediately after connection open
2. Per-scenario transaction: `BEGIN IMMEDIATE` ... `COMMIT` with `except: rollback; raise`
3. Post-seed `PRAGMA foreign_key_check` — abort on any violation
4. Post-seed consistency assertion: `SELECT lr.execution_id FROM log_records lr LEFT JOIN executions e ON lr.execution_id = e.execution_id WHERE lr.execution_id IS NOT NULL AND e.execution_id IS NULL` — abort if any rows returned. Same for `blocking_events`.
5. Generate to temp path, `os.replace()` to final path only after all checks pass

### Instance identity convention

`listeners`/`scheduled_jobs` use `(app_key, instance_index)` as the structural key. Event tables (`log_records`, `blocking_events`) also carry a denormalized `instance_name` display label. For seeding: use `instance_index` for all FK relationships, generate `instance_name` as `f"{app_class_name}.{instance_index}"` (matching the production default fallback in `app_registry.py`).

### Lifecycle field contract

Reachable state combinations for `retired_at` and `cancelled_at` on `listeners`/`scheduled_jobs`:

| State | `retired_at` | `cancelled_at` | Production path |
|---|---|---|---|
| Active | NULL | NULL | `register_listener`/`register_job` (clears both on re-registration) |
| Retired | timestamp | NULL | `reconcile_registrations` (listener not re-registered on startup) |
| Cancelled | NULL | timestamp | `mark_listener_cancelled`/`mark_job_cancelled` |
| Retired + cancelled | timestamp | timestamp | Cancelled then retired on next startup (both set sequentially) |

The `lifecycle` scenario should produce examples of all four states.

### Scenario definitions (summary)

| Scenario | Apps | Key characteristics |
|---|---|---|
| `healthy` | 5-6 | Normal activity, excellent/good health, moderate execution counts |
| `empty` | 0 | Bare schema, zero rows in all tables |
| `degraded` | 5-6 | Mixed health (some warning, some good), partial failures, at least one session with boot issues |
| `error` | 5-6 | All apps failing, high error rates, crashed sessions, boot failures |
| `large-volume` | 8-10 | Thousands of executions, large log tables, pagination needed |
| `lifecycle` | 4-5 | Retired listeners, crashed/restarted sessions, multi-instance apps, cancelled jobs, all 4 retired/cancelled states |
| `adversarial` | 3-4 | Long names (100+ chars), huge predicates, 100+ handlers per app, Unicode in names, DI failures, thread leaks, blocking events |

All scenarios use fictional app keys (e.g. `weather_watcher`, `garage_door`, `plant_monitor`).

### Existing code leverage

| Sub-problem | Existing code | Coverage |
|---|---|---|
| Create DB schema | `migration_runner.run_migrations(db_path)` | Full — reuse as-is |
| Build listener INSERT params | `repository._listener_insert_params(reg)` | Full — drop `_` prefix |
| Build execution INSERT params | `repository._execution_insert_params(record)` | Full — drop `_` prefix |
| Build job INSERT params | inline dict in `repository.register_job()` | Partial — extract to function |
| Build log_records INSERT params | `database_service._LOG_COLUMNS` + `_LOG_INSERT_SQL` | Full — drop `_` prefix, import both |
| Build blocking_events INSERT params | inline in `repository.insert_blocking_event()` | Partial — derive shape, write own INSERT |
| Create ListenerRegistration instances | `test_utils.factories.make_listener_registration()` | Full — reuse |
| Create JobRegistration instances | `test_utils.factories.make_job_registration()` | Full — reuse |
| Create ExecutionRecord instances | (none) | None — new factory needed |
| Create BlockingEvent instances | (none) | None — new factory needed |
| Create log record dicts | (none) | None — new factory needed |
| Script structure | `scripts/export_schemas.py` | Full — follow same pattern |

## Implementation Preferences

- **argparse** for CLI parsing (matching `scripts/export_schemas.py`)
- **stdlib `sqlite3`** for database access (synchronous, no aiosqlite dependency)
- **whenever** for timestamp generation (matching project convention — no `datetime`)
- All scenario data hand-authored as Python literals — no Faker, Mimesis, or RNG
- Deterministic timestamps: fixed reference point (e.g. `Instant.from_utc(2026, 1, 15, 12, 0)`) with all times as fixed offsets from that point
- `execution_id` values generated as deterministic UUIDv7-like strings (e.g. `f"{scenario}_{app_key}_{index:04d}"`) — not real UUIDs, but unique and reproducible

## Replacement Targets

No existing code is being replaced. The seed script is purely additive. The demo stack continues to exist for real-pipeline validation.

## Convention Examples

### Standalone script structure

**Source:** `scripts/export_schemas.py`

```python
#!/usr/bin/env python3
"""Export JSON Schemas for frontend type generation and config validation.

Usage::
    python scripts/export_schemas.py
"""

import argparse
import json
from pathlib import Path

def main() -> None:
    parser = argparse.ArgumentParser(description="Export schemas.")
    parser.add_argument("--types", action="store_true")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    # ...

if __name__ == "__main__":
    main()
```

### Param builder function

**Source:** `src/hassette/core/telemetry/repository.py`

```python
def _execution_insert_params(record: ExecutionRecord) -> dict[str, Any]:
    return {
        "kind": record.kind,
        "listener_id": record.listener_id,
        "job_id": record.job_id,
        "session_id": record.session_id,
        "execution_id": record.execution_id,
        "status": record.status,
        # ... all fields, booleans coerced to int
    }
```

### Test factory with keyword-only defaults

**Source:** `src/hassette/test_utils/factories.py`

```python
def make_listener_registration(
    *,
    app_key: str = DEFAULT_TEST_APP_KEY,
    instance_index: int = 0,
    handler_method: str = "test_app.on_event",
    topic: str = "hass.event.state_changed",
    debounce: float | None = None,
    # ... all fields with sensible defaults
) -> ListenerRegistration:
    return ListenerRegistration(app_key=app_key, instance_index=instance_index, ...)
```

### Migration runner (standalone, synchronous)

**Source:** `src/hassette/core/migration_runner.py`

```python
def run_migrations(db_path: Path, *, target: int | None = None) -> None:
    """Apply pending migrations to the database at db_path (synchronous)."""
    # Opens stdlib sqlite3 connection, reads .sql files, applies via executescript()
```

## Alternatives Considered

**Reuse TelemetryRepository's async methods directly** — Mechanically feasible (every method only touches `self._db_service.db`, so a `SimpleNamespace(db=conn)` duck-types cleanly). Gets free FK-tracking via `RETURNING id` and free idempotency via `ON CONFLICT`. Rejected because: requires async runtime (`asyncio.run`), and `insert_blocking_event` silently swallows DB failures — the opposite of the "break loudly" property needed in a data generation tool.

**Raw hand-typed SQL with no param builder reuse** — Fully synchronous, no import coupling. Rejected because: this is exactly the anti-pattern (hand-patched seed SQL drifting from schema) documented in the prior art research. When a migration adds a column, the seed script silently omits it instead of failing.

**Checked-in .db files** — Instant access, no generation step needed. Rejected for now because: binary blobs in git can't be diffed or reviewed, and someone has to remember to regenerate after migrations. Can revisit if instant access becomes a concrete need.

**Faker/Mimesis for synthetic data** — Standard for large-volume generation. Rejected because: introduces a dependency for a dev script, and even with pinned seeds, output changes when the library version bumps. Hand-authored deterministic data is more appropriate for 7 scenarios with fixed shapes.

## Test Strategy

### Existing Tests to Adapt

- `tests/integration/telemetry/test_telemetry_execution_id.py` — imports `_execution_insert_params` directly (lines 13, 149, 208). Update import to `execution_insert_params` after rename.
- `tests/integration/test_thread_leaked_observability.py` — references `_execution_insert_params` in docstring/comment prose (lines 306, 317). Update comments to match the renamed function.

### New Test Coverage

- **Unit tests for param builder extraction**: verify that `job_insert_params()` produces the same dict as the inline logic in `register_job()`, with `repeat=0` hardcoded. Verify the renamed `execution_insert_params` and `listener_insert_params` still produce identical output.
- **Scenario generation smoke test** (AC#5): parametrized test that runs each of the 7 scenarios and asserts exit 0 + non-empty DB (except `empty` which asserts zero rows). Integration test layer.
- **Determinism test** (AC#2): run the same scenario twice, compare `SELECT * FROM <table> ORDER BY id` output for all tables. Integration test layer.
- **FK violation detection test** (AC#3): intentionally insert a bad `listener_id`, assert the script aborts. Unit test layer.
- **Consistency assertion test** (AC#4): intentionally insert a dangling `execution_id` in `log_records`, assert the script aborts. Unit test layer.

### Tests to Remove

No tests to remove.

## Documentation Updates

- **CLAUDE.md**: add a section under Common Commands for the seed script usage (`uv run python scripts/seed_db.py --scenario healthy --output /path/to/db`)
- **Issue #854**: close with reference to the implementing PR
- **Issue #1125** (separate demo apps): may be partially superseded — update with a note once the seed script ships

## Impact

### Changed Files

- **create** `scripts/seed_db.py` — the seed script (scenario registry, SeedContext, scenario generators, integrity checks, CLI)
- **modify** `src/hassette/core/telemetry/repository.py` — drop `_` prefix on `_execution_insert_params` and `_listener_insert_params`; extract `job_insert_params` from `register_job()` inline logic
- **modify** `src/hassette/test_utils/factories.py` — add `make_execution_record()`, `make_blocking_event()`, and `make_log_record()` factories
- **modify** `tests/integration/telemetry/test_telemetry_execution_id.py` — update import from `_execution_insert_params` to `execution_insert_params`
- **modify** `tests/integration/test_thread_leaked_observability.py` — update docstring/comment references to `_execution_insert_params`
- **create** tests for param builder extraction and scenario generation

### Behavioral Invariants

- `TelemetryRepository.register_listener()`, `register_job()`, and `persist_execution_batch()` must continue to work identically after the param builder rename (they call the same functions, just without the `_` prefix)
- Existing test factories `make_listener_registration()` and `make_job_registration()` must not change behavior

### Blast Radius

- The param builder rename (`_execution_insert_params` → `execution_insert_params`) affects `repository.py` internal callers and one test file (`tests/integration/telemetry/test_telemetry_execution_id.py`) that imports it directly
- The new `make_execution_record()` factory is additive
- The seed script itself has no runtime consumers — it's a dev tool

## Open Questions

None — all questions resolved during grill, challenge, and discovery phases.
