# Brief: Deterministic DB Seeding Script

**Date:** 2026-07-25
**Status:** explored

## Idea

A standalone script (`scripts/seed_db.py`) that populates the hassette telemetry database with deterministic synthetic data for named scenarios. Each scenario produces a complete, self-consistent dataset across all telemetry tables (sessions, listeners, jobs, executions, log_records, blocking_events). The script imports from `hassette.core` to reuse the real column-shape definitions (param builders, frozen dataclasses) but does not start the hassette runtime — it opens a raw sqlite3 connection, runs migrations, and does direct INSERTs. Scenario outputs are generated on demand, not checked into git.

Consumers: CLI doc generation (#855), frontend dev QA (#760 Phase 3), visual regression screenshots, demos. The demo stack continues to exist for real-pipeline validation; seed data is for controllable, instant UI state QA.

## Key Decisions Made

- **Script generates on demand, no checked-in DB files.** Can revisit later if there's a benefit to checking in outputs. Each run always produces a fresh file (delete existing → migrate → seed → atomic swap). No in-place re-run or upsert logic — avoid INSERT OR REPLACE which silently corrupts IDs.
- **MSW covers transport-level scenarios only** (disconnects, 500s, latency). Seed DB covers data-shape scenarios. Clean separation, no duplication of "make the frontend look like X."
- **Import param builders from hassette.core, but write a sync insert helper in the seed script.** The param builders (`_execution_insert_params`, `_listener_insert_params`) are pure functions (dataclass in, dict out) — drop the underscore prefix to make them importable. Extract `_job_insert_params` from the inline logic in `register_job`. The seed script writes one thin `insert_row(cursor, table, params)` helper that does `cursor.execute(INSERT ... RETURNING id)` — gets column-shape reuse without the async runtime or the error-swallowing behavior of the full repository methods.
- **Raw sqlite3 + migration runner** for writes. No async runtime needed — the param builders are synchronous, and the seed script's insert helper is plain sqlite3. The seeder's connection must set `PRAGMA foreign_keys = ON` immediately after opening, and run `PRAGMA foreign_key_check` as a hard gate after seeding completes (SQLite defaults FK enforcement to OFF per-connection).
- **Full table graph** from day one — sessions, listeners, jobs, executions, log_records, blocking_events. No incremental table rollout.
- **Fictional app keys** — invented names (not tied to example apps in `examples/`). Decoupled from demo stack, can't drift.
- **Over-seed past health thresholds** — error rates well past the warning/critical boundaries so minor threshold adjustments don't change displayed states. Follow-up: contract tests that load seed DBs and assert expected health statuses.
- **Keep error and degraded as separate scenarios** — they exercise different UI states (warning vs critical). Error = everything failing. Degraded = mixed health, some apps struggling.
- **Health status stays computed live** (not materialized in DB). The seeding inconvenience doesn't justify an architecture change.
- **Demo stack stays** for real-pipeline validation. Seed data is supplementary, not a replacement.

## Open Questions

- **Exact scenario list.** Starting set is ~7 scenarios: healthy, empty, large-volume, degraded, error, plus 1-2 for lifecycle (retired listeners, crashed sessions, multi-instance) and edge-cases/adversarial (long names, huge predicates, 100s of handlers, Unicode, DI failures, thread leaks, blocking events). Exact breakdown TBD in /mine-define.
- **HA-optional startup mode.** Hassette currently crashes at boot if HA is unreachable — the web server never binds. Seed DBs can't simplify the screenshot pipeline until hassette can serve the dashboard without HA. Filing as a separate issue.
- **Contract tests shape.** The "load seed DB, run health computation, assert expected status" tests need design — where do they live, how are they structured, do they run in CI?
- **`_job_insert_params` extraction.** Job inserts are currently inline in the repository (unlike listener/execution which have dedicated param builders). Needs extraction as part of the shared-module refactor.
- **CHECK-constraint parity.** `ExecutionRecord.status` (and other CHECK-backed string fields like `sessions.status`, `listeners.source_tier`, `scheduled_jobs.trigger_type`) are typed as plain `str` — no type-checker signal when a migration adds a new legal value. Promote to `Literal` types matching each CHECK constraint, with a test asserting parity between the Python `Literal` and the SQL CHECK values. Prevents new states going permanently unexercised.

## Scope Boundaries

**In scope:**
- `scripts/seed_db.py` with `--scenario <name>` flag
- Named-scenario registry (a plain dict literal mapping names to generator callables — no enum, plugin discovery, or directory-per-scenario layout until a concrete second consumer needs it)
- Drop underscore prefix on `_execution_insert_params` and `_listener_insert_params` in `repository.py`; extract `_job_insert_params` from inline logic in `register_job`
- Adding missing factories (`ExecutionRecord`, `BlockingEvent`, log records)
- All 6 telemetry tables populated with referentially consistent data
- An intermediate builder/context type (`SeedGraph` or similar) that owns cross-table ID bookkeeping and insert ordering, so scenario generators don't each re-derive the session→listener/job→execution→log/blocking-event plumbing
- Each scenario's full insert sequence wrapped in one `BEGIN IMMEDIATE`/`COMMIT` with rollback on error; generate into a temp path, swap via `os.replace()` only after transaction commits and `PRAGMA foreign_key_check` passes
- Post-seed consistency assertion: a LEFT JOIN query that fails the run on any dangling non-null `execution_id` in `log_records`/`blocking_events` (these columns have no FK constraint by design — write-ordering in production prevents it, but the seeder has no such constraint)
- ~7 scenarios covering healthy, empty, large-volume, degraded, error, lifecycle, adversarial

**Explicitly out of scope:**
- Checked-in DB files (revisit later)
- CI freshness checks for seed DBs
- HA-optional startup mode (separate issue)
- MSW browser scenarios (#760 Phase 1-2 — independent work)
- Changes to the demo stack
- CLI `hassette seed` subcommand (this is a dev script, not a shipped CLI surface)

**Deferred:**
- Contract tests asserting seed scenario health statuses
- Integration with screenshot capture pipeline (blocked on HA-optional mode)
- Wiring seed scenarios into #760's dev panel (Phase 3 of that issue)

## Risks and Concerns

- **Schema drift** — the param-builder refactor mitigates this (generator breaks loudly when a migration adds a column), but the seeder is still a second consumer of the column shapes. A migration author who updates the repository but forgets the seeder will get a failing seed script, not a silent bug. This is the desired behavior.
- **Object Mother coupling** — once screenshot tests or frontend tests depend on exact row counts or specific error messages from a scenario, changing the scenario becomes a breaking change. Mitigation: keep scenario contracts as documented invariants ("degraded always shows warning health"), not exact literals.
- **Referential integrity complexity** — the script must orchestrate inserts in order (sessions → listeners/jobs → executions → log_records/blocking_events) and track auto-generated IDs. This is the most complex part of the implementation.
- **Dashboard manifest gap** — The dashboard grid and apps list are driven by in-memory app manifests (`runtime.get_all_manifests_snapshot()`), not the telemetry DB. Fictional app keys with no loaded manifest are invisible on the two screens most QA workflows start from. Per-app detail pages query the DB directly and work fine. This is an architectural flaw independent of seeding (historical data for unloaded apps is also invisible) — filed as a separate issue. Until resolved, seed DBs are useful for per-app detail pages, CLI docs, and component-level frontend tests, but not full-dashboard screenshots or demos.
- **Adversarial data rendering** — long names, huge predicates, and 100s of handlers may reveal real UI bugs. The seed script is the delivery mechanism, but the fixes live in the frontend.

## Codebase Context

- **Migration runner** (`src/hassette/core/migration_runner.py`): fully standalone, synchronous, stdlib sqlite3. `run_migrations(db_path)` creates the full schema with zero framework bootstrapping. Ready to reuse as-is.
- **Param builders** (`src/hassette/core/telemetry/repository.py`): `_execution_insert_params(ExecutionRecord) → dict` and `_listener_insert_params(ListenerRegistration) → dict` are module-level functions (not methods). Job inserts are inline. These need extraction to a shared module.
- **Frozen dataclasses**: `ExecutionRecord` (~20 fields, maps 1:1 to executions table), `ListenerRegistration`, `ScheduledJobRegistration` — these are the intermediate data shapes for seeding.
- **Test factories** (`src/hassette/test_utils/factories.py`): `make_listener_registration()` and `make_job_registration()` exist. No factory for `ExecutionRecord`, `BlockingEvent`, or log records.
- **Health computation** (`src/hassette/web/telemetry_helpers.py`): `HealthStatus` (excellent/good/warning/critical) derived from execution success rates. Not stored — computed at query time.
- **DB path**: configurable via `DatabaseConfig.path` or defaults to `config.data_dir / "hassette.db"`.
- **`scheduled_jobs.repeat`**: hardcoded to `0` in `register_job`'s inline INSERT (`repository.py:396-399`). No CHECK constraint protects this invariant. If `_job_insert_params` is extracted, `repeat` must stay hardcoded, not become a parameter.
- **Instance identity**: `listeners`/`scheduled_jobs` use `(app_key, instance_index)` as the structural key. Event tables (`log_records`, `blocking_events`) carry both `instance_index` AND a denormalized `instance_name` display label. `instance_name` defaults to `f"{class_name}.{index}"` but is user-overridable. The seeder should pick a deterministic `instance_name` per instance and use `instance_index` for all FK relationships.
- **Lifecycle field state contract**: `retired_at` and `cancelled_at` on listeners/jobs have no CHECK constraint — any combination is writable. In production, only specific code paths set them: `reconcile_registrations` sets `retired_at` (listener not re-registered on startup); `mark_listener_cancelled`/`mark_job_cancelled` sets `cancelled_at`; `register_listener`/`register_job` clears both on re-registration. Lifecycle scenario generators must document which combinations they're producing and why they're reachable.
- **Prior art research**: saved at `design/research/2026-07-25-deterministic-db-seeding/research.md`.
